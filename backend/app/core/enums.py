"""Every value the system branches on lives here as an enum.

No magic strings: if a string is compared, persisted as a discriminator, or sent
to a vendor API, it gets a member in this module.
"""

from enum import StrEnum


class AppEnv(StrEnum):
    """Selects which `.env.<value>` file is loaded. See `core.config`."""

    LOCAL = "local"
    PROD = "prod"


class Language(StrEnum):
    """BCP-47 codes as Sarvam expects them.

    Limited to the set `mayura:v1` translates bidirectionally. Widening this to
    all 22 official languages means switching to `sarvam-translate:v1`, which
    has a more formal register — see docs/PLAN.md section 7.4.
    """

    ENGLISH = "en-IN"
    HINDI = "hi-IN"
    BENGALI = "bn-IN"
    TAMIL = "ta-IN"
    TELUGU = "te-IN"
    GUJARATI = "gu-IN"
    KANNADA = "kn-IN"
    MALAYALAM = "ml-IN"
    MARATHI = "mr-IN"
    PUNJABI = "pa-IN"
    ODIA = "od-IN"


#: Spoken names for IVR prompts and admin display. Kept beside the enum so a new
#: language cannot be added without naming it.
LANGUAGE_DISPLAY_NAMES: dict[Language, str] = {
    Language.ENGLISH: "English",
    Language.HINDI: "Hindi",
    Language.BENGALI: "Bengali",
    Language.TAMIL: "Tamil",
    Language.TELUGU: "Telugu",
    Language.GUJARATI: "Gujarati",
    Language.KANNADA: "Kannada",
    Language.MALAYALAM: "Malayalam",
    Language.MARATHI: "Marathi",
    Language.PUNJABI: "Punjabi",
    Language.ODIA: "Odia",
}

#: DTMF fallback for language selection, for callers whose speech is not
#: recognised. Ordered by expected traffic; speech input is the primary path.
LANGUAGE_DTMF_MENU: dict[str, Language] = {
    "1": Language.HINDI,
    "2": Language.TAMIL,
    "3": Language.TELUGU,
    "4": Language.KANNADA,
    "5": Language.MALAYALAM,
    "6": Language.MARATHI,
    "7": Language.BENGALI,
    "8": Language.ENGLISH,
}


class TranslationMode(StrEnum):
    """Sarvam `mode`. CODE_MIXED is how the secondary language is honoured.

    A user with primary=Hindi, secondary=English gets Hinglish: technical nouns
    preserved in English rather than forced into pure Hindi.
    """

    FORMAL = "formal"
    CLASSIC_COLLOQUIAL = "classic-colloquial"
    MODERN_COLLOQUIAL = "modern-colloquial"
    CODE_MIXED = "code-mixed"


class OutputScript(StrEnum):
    """Sarvam `output_script`. Native script is what TTS wants."""

    ROMAN = "roman"
    FULLY_NATIVE = "fully-native"
    SPOKEN_FORM_IN_NATIVE = "spoken-form-in-native"


class LegState(StrEnum):
    """IVR state machine. Transitions are declared in `services.ivr_service`."""

    IDENTIFY = "identify"
    ASK_LANGUAGES = "ask_languages"
    MENU = "menu"
    ROOM_CREATED = "room_created"
    WAIT_PEER = "wait_peer"
    ASK_ROOM_CODE = "ask_room_code"
    ASK_NUMBER = "ask_number"
    DIALING_PEER = "dialing_peer"
    BRIDGED = "bridged"
    ENDED = "ended"


class LegDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class PairingMode(StrEnum):
    """How the second leg joined. Maps to the main-menu keys."""

    ROOM_CODE = "room_code"
    DIAL_OUT = "dial_out"


class CallStatus(StrEnum):
    PENDING = "pending"
    BRIDGED = "bridged"
    COMPLETED = "completed"
    FAILED = "failed"


class RoomStatus(StrEnum):
    WAITING = "waiting"
    PAIRED = "paired"
    EXPIRED = "expired"


class MenuKey(StrEnum):
    """Main-menu DTMF keys, spoken in the caller's primary + secondary language."""

    CREATE_ROOM = "1"
    DIAL_NUMBER = "2"
    JOIN_ROOM = "3"
    CHANGE_LANGUAGE = "9"


class SttMode(StrEnum):
    """Sarvam realtime STT `mode`.

    TRANSCRIBE is the default. Two others matter to this project:

    VERBATIM keeps disfluencies and broken grammar instead of tidying them,
    which is closer to the fidelity requirement but risks speaking a listener
    every "um" the speaker made. Worth an A/B in the Phase 2 eval.

    TRANSLATE emits English directly from source audio. That is the free first
    hop of the Indic->Indic pivot (PLAN 7.4.2) - the single biggest latency win
    available, deferred to Phase 8.
    """

    TRANSCRIBE = "transcribe"
    VERBATIM = "verbatim"
    TRANSLATE = "translate"
    TRANSLIT = "translit"
    CODEMIX = "codemix"


class SttStreamType(StrEnum):
    """Latency/accuracy trade-off on Sarvam's realtime endpoint."""

    FAST = "fast"
    BALANCED = "balanced"
    SIMULATED = "simulated"


class PipelineMode(StrEnum):
    """Which pipeline a leg gets. Phase 4 replaces this with real pairing.

    Until then it is how you choose what a test call does.
    """

    #: Phase 1: hear your own voice back. Proves transport only.
    ECHO = "echo"
    #: Phase 2: hear yourself translated. Proves the full AI path on one leg.
    TRANSLATE_LOOPBACK = "translate_loopback"


class SarvamSpeaker(StrEnum):
    """Voices available on bulbul:v3.

    Speaker names are model-generation specific: the v2 voices (anushka,
    abhilash, manisha, vidya, arya, karun, hitesh) are NOT valid for v3, and
    pairing one with v3 fails at request time. Naming them here rather than
    inlining strings is what stops that recurring.
    """

    ADITYA = "aditya"
    RITU = "ritu"
    PRIYA = "priya"
    NEHA = "neha"
    RAHUL = "rahul"
    POOJA = "pooja"
    ROHAN = "rohan"
    SIMRAN = "simran"
    KAVYA = "kavya"
    AMIT = "amit"
    DEV = "dev"
    ISHITA = "ishita"
    SHREYA = "shreya"
    RATAN = "ratan"
    VARUN = "varun"
    MANAN = "manan"
    SUMIT = "sumit"
    ROOPA = "roopa"
    KABIR = "kabir"
    AAYAN = "aayan"
    SHUBH = "shubh"
    ASHUTOSH = "ashutosh"
    ADVAIT = "advait"
    AMELIA = "amelia"
    SOPHIA = "sophia"


class AudioCodec(StrEnum):
    """Wire formats shared by Vobiz streaming and Sarvam TTS.

    MULAW_8K is the happy path: Vobiz speaks it natively and Sarvam TTS can emit
    it directly, so no resampling sits in the latency budget.
    """

    MULAW_8000 = "mulaw"
    LINEAR16_8000 = "linear16_8000"
    LINEAR16_16000 = "linear16_16000"
