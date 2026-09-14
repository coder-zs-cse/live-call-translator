"""The IVR state machine.

One method per caller input. Each decides what happens next, records the new
`LegState`, and returns an `IvrDirective` — never XML, never a Response. That is
what lets the whole menu be tested without a phone or a parser.

The state diagram is in docs/PLAN.md §4.2. In short:

    IDENTIFY -> ASK_LANGUAGES (new caller only) -> MENU -> {room, dial, join}
                                                        -> BRIDGED

An outbound leg — someone the AI dialled — skips MENU entirely: they did not ask
for a menu, they answered a ringing phone.
"""

from __future__ import annotations

import uuid

from app.core.config import CallSettings
from app.core.enums import (
    LANGUAGE_DISPLAY_NAMES,
    Language,
    LegDirection,
    LegState,
    MenuKey,
)
from app.core.exceptions import RoomNotFoundError
from app.core.logging import get_logger
from app.ivr.catalog import PromptKey, speak_digits
from app.ivr.directives import GatherSpec, IvrDirective
from app.ivr.prompt_service import PromptService
from app.models.call import CallLeg
from app.repositories.interfaces import ICallLegRepository, IUserRepository
from app.schemas.telephony import GatherWebhook, InboundCallWebhook
from app.services.language_service import (
    language_from_input,
    needs_language_setup,
    speech_hints,
)
from app.services.pairing_service import PairingService

logger = get_logger(__name__)

# Action paths the <Gather> elements post back to. Named constants because they
# appear in both the router and here, and a typo would be a dead-end call.
PATH_LANGUAGE_PRIMARY = "/api/v1/xml/language/primary"
PATH_LANGUAGE_SECONDARY = "/api/v1/xml/language/secondary"
PATH_MENU = "/api/v1/xml/menu"
PATH_ROOM_CODE = "/api/v1/xml/room-code"
PATH_PHONE_NUMBER = "/api/v1/xml/phone-number"
PATH_WAIT = "/api/v1/xml/wait"

#: Longest Indian mobile number plus country code, entered before the # key.
_MAX_PHONE_DIGITS = 15
_ROOM_CODE_DIGITS = 8

#: How long one waiting poll blocks before the creator is asked again. Short
#: enough that a joined peer is noticed quickly, long enough not to hammer the
#: webhook.
_WAIT_POLL_SECONDS = 5


class IvrService:
    def __init__(
        self,
        *,
        users: IUserRepository,
        legs: ICallLegRepository,
        pairing: PairingService,
        prompts: PromptService,
        call_settings: CallSettings,
    ) -> None:
        self._users = users
        self._legs = legs
        self._pairing = pairing
        self._prompts = prompts
        self._call_settings = call_settings

    # --- entry -------------------------------------------------------------

    async def on_answer(self, webhook: InboundCallWebhook) -> IvrDirective:
        """A leg connected. Create it, then ask languages or show the menu."""
        direction = (
            LegDirection.OUTBOUND
            if webhook.direction.lower().startswith("out")
            else LegDirection.INBOUND
        )

        user = await self._users.get_by_phone(webhook.from_number)
        if user is None:
            user = await self._users.create(webhook.from_number)

        leg = await self._legs.get_by_provider_uuid(webhook.call_uuid)
        if leg is None:
            leg = await self._legs.create(
                provider_call_uuid=webhook.call_uuid,
                phone_e164=webhook.from_number,
                direction=direction,
                user_id=user.id,
            )
        await self._users.touch_last_call(user.id)

        if needs_language_setup(user.primary_language, user.secondary_language):
            await self._legs.set_state(leg.id, LegState.ASK_LANGUAGES)
            return self._ask_primary_language()

        # An outbound leg was dialled by someone who is already waiting, so it
        # goes straight to the conversation rather than through a menu.
        if direction is LegDirection.OUTBOUND:
            primary = user.primary_language or self._call_settings.default_primary_language
            secondary = user.secondary_language or self._call_settings.default_secondary_language
            leg = await self._legs.snapshot_languages(leg.id, primary=primary, secondary=secondary)
            await self._legs.set_state(leg.id, LegState.BRIDGED)
            return IvrDirective(
                speak=self._bilingual_in(PromptKey.CONNECTED, primary, secondary),
                bridge=True,
            )

        primary = user.primary_language or self._call_settings.default_primary_language
        secondary = user.secondary_language or self._call_settings.default_secondary_language
        leg = await self._legs.snapshot_languages(leg.id, primary=primary, secondary=secondary)
        await self._legs.set_state(leg.id, LegState.MENU)
        return self._main_menu(leg)

    # --- language setup ----------------------------------------------------

    async def on_primary_language(self, webhook: GatherWebhook) -> IvrDirective:
        language = language_from_input(digits=webhook.digits, speech=webhook.speech)
        if language is None:
            # Re-ask rather than guess. A wrong language here poisons every
            # later call from this number.
            return IvrDirective(
                speak=[self._english(PromptKey.LANGUAGE_NOT_UNDERSTOOD)],
                gather=self._language_gather(PATH_LANGUAGE_PRIMARY),
            )

        leg = await self._require_leg(webhook.call_uuid)
        # Secondary defaults to English and is confirmed in the next question;
        # storing it now means an abandoned call still leaves a usable user.
        await self._users.set_languages(
            self._user_id(leg),
            primary=language,
            secondary=self._call_settings.default_secondary_language,
        )
        logger.info("primary_language_set", leg_id=str(leg.id), language=language.value)

        return IvrDirective(
            speak=[
                self._english(PromptKey.LANGUAGE_SAVED),
                LANGUAGE_DISPLAY_NAMES[language],
            ],
            gather=self._language_gather(PATH_LANGUAGE_SECONDARY, num_digits=1),
        )

    async def on_secondary_language(self, webhook: GatherWebhook) -> IvrDirective:
        leg = await self._require_leg(webhook.call_uuid)
        user = await self._users.get_by_phone(leg.phone_e164)
        primary = (user.primary_language if user else None) or (
            self._call_settings.default_primary_language
        )

        # "1" is the fast path: keep English, which is what almost everyone
        # wants and what the prompt offers first.
        if webhook.digits and webhook.digits.strip() == "1":
            secondary = Language.ENGLISH
        else:
            secondary = language_from_input(digits=None, speech=webhook.speech) or Language.ENGLISH

        await self._users.set_languages(self._user_id(leg), primary=primary, secondary=secondary)
        leg = await self._legs.snapshot_languages(leg.id, primary=primary, secondary=secondary)
        logger.info(
            "languages_set",
            leg_id=str(leg.id),
            primary=primary.value,
            secondary=secondary.value,
        )

        # An outbound leg never wanted a menu; it was dialled into a call that
        # is already waiting for it.
        if leg.direction is LegDirection.OUTBOUND:
            await self._legs.set_state(leg.id, LegState.BRIDGED)
            return IvrDirective(
                speak=self._bilingual_in(PromptKey.CONNECTED, primary, secondary),
                bridge=True,
            )

        await self._legs.set_state(leg.id, LegState.MENU)
        return IvrDirective(
            speak=self._bilingual_in(PromptKey.MAIN_MENU, primary, secondary),
            gather=GatherSpec(action_path=PATH_MENU, num_digits=1),
        )

    # --- main menu ---------------------------------------------------------

    async def on_menu_choice(self, webhook: GatherWebhook) -> IvrDirective:
        leg = await self._require_leg(webhook.call_uuid)
        choice = (webhook.digits or "").strip()

        if choice == MenuKey.CREATE_ROOM:
            code = await self._pairing.create_room(leg.id)
            await self._pairing.begin_wait(leg.id)
            await self._legs.set_state(leg.id, LegState.WAIT_PEER)
            return IvrDirective(
                speak=[
                    *self._bilingual(PromptKey.ROOM_CODE_IS, leg),
                    speak_digits(code),
                    *self._bilingual(PromptKey.WAITING_FOR_PEER, leg),
                ],
                gather=self._wait_gather(),
            )

        if choice == MenuKey.JOIN_ROOM:
            await self._legs.set_state(leg.id, LegState.ASK_ROOM_CODE)
            return IvrDirective(
                speak=self._bilingual(PromptKey.ASK_ROOM_CODE, leg),
                gather=GatherSpec(action_path=PATH_ROOM_CODE, num_digits=_ROOM_CODE_DIGITS),
            )

        if choice == MenuKey.DIAL_NUMBER:
            await self._legs.set_state(leg.id, LegState.ASK_NUMBER)
            return IvrDirective(
                speak=self._bilingual(PromptKey.ASK_PHONE_NUMBER, leg),
                gather=GatherSpec(action_path=PATH_PHONE_NUMBER, num_digits=_MAX_PHONE_DIGITS),
            )

        if choice == MenuKey.CHANGE_LANGUAGE:
            await self._legs.set_state(leg.id, LegState.ASK_LANGUAGES)
            return self._ask_primary_language()

        return IvrDirective(
            speak=[
                *self._bilingual(PromptKey.INVALID_CHOICE, leg),
                *self._bilingual(PromptKey.MAIN_MENU, leg),
            ],
            gather=GatherSpec(action_path=PATH_MENU, num_digits=1),
        )

    # --- pairing -----------------------------------------------------------

    async def on_room_code(self, webhook: GatherWebhook) -> IvrDirective:
        leg = await self._require_leg(webhook.call_uuid)
        code = (webhook.digits or "").strip()

        try:
            await self._pairing.join_room(leg_id=leg.id, code=code)
        except RoomNotFoundError:
            # Deliberately identical for unknown, expired and already-claimed
            # codes: telling them apart would help someone guess.
            return IvrDirective(
                speak=self._bilingual(PromptKey.ROOM_NOT_FOUND, leg),
                gather=GatherSpec(action_path=PATH_ROOM_CODE, num_digits=_ROOM_CODE_DIGITS),
            )

        await self._legs.set_state(leg.id, LegState.BRIDGED)
        return IvrDirective(speak=self._bilingual(PromptKey.CONNECTED, leg), bridge=True)

    async def on_wait_poll(self, webhook: GatherWebhook) -> IvrDirective:
        """The room creator, checking whether anyone has joined yet.

        Implemented as a repeating <Gather> whose timeout is the poll interval,
        so the caller is held on a quiet line instead of a busy loop.
        """
        leg = await self._require_leg(webhook.call_uuid)

        # PairingService moves this leg to BRIDGED the moment a peer claims the
        # room, so the poll is just watching for that write.
        if leg.state is LegState.BRIDGED:
            return IvrDirective(speak=self._bilingual(PromptKey.CONNECTED, leg), bridge=True)

        return IvrDirective(gather=self._wait_gather())

    async def on_phone_number(self, webhook: GatherWebhook) -> tuple[IvrDirective, str | None]:
        """Returns the directive plus the number to dial, if one was entered.

        Placing the outbound call is I/O against the carrier, which belongs to
        the API layer's telephony client rather than to the state machine.
        """
        leg = await self._require_leg(webhook.call_uuid)
        digits = (webhook.digits or "").strip()

        if not digits:
            return (
                IvrDirective(
                    speak=self._bilingual(PromptKey.ASK_PHONE_NUMBER, leg),
                    gather=GatherSpec(action_path=PATH_PHONE_NUMBER, num_digits=_MAX_PHONE_DIGITS),
                ),
                None,
            )

        await self._pairing.start_dial_out(leg.id)
        await self._pairing.begin_wait(leg.id)
        await self._legs.set_state(leg.id, LegState.DIALING_PEER)

        return (
            IvrDirective(
                speak=self._bilingual(PromptKey.DIALING_NOW, leg),
                gather=self._wait_gather(),
            ),
            digits,
        )

    # --- helpers -----------------------------------------------------------

    def _ask_primary_language(self) -> IvrDirective:
        """Always English: we do not yet know what else they understand."""
        return IvrDirective(
            speak=[self._english(PromptKey.ASK_PRIMARY_LANGUAGE)],
            gather=self._language_gather(PATH_LANGUAGE_PRIMARY),
        )

    def _main_menu(self, leg: CallLeg) -> IvrDirective:
        return IvrDirective(
            speak=self._bilingual(PromptKey.MAIN_MENU, leg),
            gather=GatherSpec(action_path=PATH_MENU, num_digits=1),
        )

    def _language_gather(self, action_path: str, *, num_digits: int = 1) -> GatherSpec:
        return GatherSpec(
            action_path=action_path,
            num_digits=num_digits,
            accept_speech=True,
            hints=speech_hints(),
            execution_timeout=12,
        )

    def _wait_gather(self) -> GatherSpec:
        return GatherSpec(
            action_path=PATH_WAIT,
            num_digits=1,
            execution_timeout=_WAIT_POLL_SECONDS,
        )

    def _english(self, key: PromptKey) -> str:
        return self._prompts.text(key, Language.ENGLISH)

    def _bilingual(self, key: PromptKey, leg: CallLeg) -> list[str]:
        primary = leg.language_primary or self._call_settings.default_primary_language
        secondary = leg.language_secondary or self._call_settings.default_secondary_language
        return self._bilingual_in(key, primary, secondary)

    def _bilingual_in(self, key: PromptKey, primary: Language, secondary: Language) -> list[str]:
        return self._prompts.bilingual(key, primary=primary, secondary=secondary)

    async def _require_leg(self, provider_call_uuid: str) -> CallLeg:
        leg = await self._legs.get_by_provider_uuid(provider_call_uuid)
        if leg is None:
            raise RoomNotFoundError(f"no leg for call {provider_call_uuid}")
        return leg

    @staticmethod
    def _user_id(leg: CallLeg) -> uuid.UUID:
        if leg.user_id is None:
            raise RoomNotFoundError(f"leg {leg.id} has no user")
        return leg.user_id
