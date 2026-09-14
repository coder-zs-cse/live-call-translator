"""chrF is hand-rolled to keep the eval dependency-free, so pin its behaviour
against cases where the right answer is obvious."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval_translation import chrf  # noqa: E402


def test_identical_strings_score_100() -> None:
    assert chrf("मुझे स्टेशन जाना है", "मुझे स्टेशन जाना है") == 100.0


def test_completely_different_strings_score_zero() -> None:
    assert chrf("aaaaaaaa", "bbbbbbbb") == 0.0


def test_partial_overlap_scores_between() -> None:
    score = chrf("முழு வாக்கியம் இங்கே", "முழு வாக்கியம் அங்கே")
    assert 0.0 < score < 100.0


def test_whitespace_is_ignored() -> None:
    """chrF operates on characters with spaces stripped, so spacing differences
    must not be penalised."""
    assert chrf("hello world", "helloworld") == 100.0


def test_empty_hypothesis_scores_zero() -> None:
    assert chrf("", "something") == 0.0
