"""Тесты сопоставления category_N с полем справочника по ключу.

Суть проверки: два поля справочника принимают одни и те же значения (YES/NO),
поэтому по набору значений они неразличимы. Различает их только совпадение
ПО КЛЮЧУ — вот это и проверяется.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match_categories import agreement, normalize  # noqa: E402


def test_identical_value_sets_are_told_apart_by_key():
    """Ровно тот случай, ради которого скрипт и написан."""
    keys = [f"tv_{i}" for i in range(100)]
    truth = pd.Series(["yes"] * 60 + ["no"] * 40, index=keys)

    # Правильная колонка: те же значения на тех же ключах.
    right = truth.copy()
    # Неправильная: тот же НАБОР значений, но разложены иначе.
    wrong = pd.Series(["no"] * 60 + ["yes"] * 40, index=keys)

    assert set(right) == set(wrong) == {"yes", "no"}

    right_share, _ = agreement(truth, right)
    wrong_share, _ = agreement(truth, wrong)

    assert right_share == 1.0
    assert wrong_share == 0.0


def test_keys_missing_from_the_dictionary_do_not_count():
    """Строка, которой нет в справочнике, ничего не говорит о колонке."""
    truth = pd.Series(["yes", "no", pd.NA], index=["a", "b", "c"], dtype="string")
    candidate = pd.Series(["yes", "no", "yes"], index=["a", "b", "c"], dtype="string")

    share, compared = agreement(truth, candidate)

    assert compared == 2
    assert share == 1.0


def test_nothing_in_common_is_not_a_match():
    truth = pd.Series(["yes"], index=["a"], dtype="string")
    candidate = pd.Series(["yes"], index=["b"], dtype="string")

    share, compared = agreement(truth, candidate.reindex(truth.index))

    assert compared == 0
    assert share == 0.0


def test_case_and_spaces_do_not_break_the_comparison():
    """В базе значения прописными, в справочнике строчными."""
    truth = normalize(pd.Series(["yes", "no"], index=["a", "b"]))
    candidate = normalize(pd.Series([" YES ", "No"], index=["a", "b"]))

    share, compared = agreement(truth, candidate)

    assert compared == 2
    assert share == 1.0


def test_empty_strings_count_as_unknown_not_as_a_value():
    truth = normalize(pd.Series(["yes", "no"], index=["a", "b"]))
    candidate = normalize(pd.Series(["yes", ""], index=["a", "b"]))

    share, compared = agreement(truth, candidate)

    # Пустое значение — это «неизвестно», а не несовпадение.
    assert compared == 1
    assert share == 1.0
