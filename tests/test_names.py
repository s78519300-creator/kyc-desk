import pytest

from kyc_desk.names import same_person, similarity


@pytest.mark.parametrize("a,b", [
    ("Ramesh Kumar", "R. Kumar"),
    ("RAMESH KUMAR", "Ramesh Kr"),
    ("Mohd. Irfan Shaikh", "MOHAMMED IRFAN SHAIKH"),
    ("Ramesh Kumar Singh", "Ramesh Singh"),
    ("Singh Ramesh", "Ramesh Singh"),
    ("r.k. sharma", "RAJESH KUMAR SHARMA"),
])
def test_same_person_accepts_policy_variations(a, b):
    assert same_person(a, b) and same_person(b, a)


@pytest.mark.parametrize("a,b", [
    ("Ramesh Kumar Singh", "Ramesh Kumar"),   # missing surname
    ("Ramesh Kumar", "Suresh Kumar"),         # different first name
    ("Priya Sharma", "Priya Verma"),          # different surname
    ("A Sharma", "B Sharma"),
    ("Kumar Singh", "Ramesh Kumar Singh"),    # missing first name
])
def test_same_person_rejects_different_people(a, b):
    assert not same_person(a, b)


def test_similarity_credits_initials():
    assert similarity("Zubair Qureshi", "Zubair Qureshi") == 1.0
    assert similarity("Z. Qureshi", "Zubair Qureshi") == 0.75
    assert similarity("Priya Sharma", "Zubair Qureshi") == 0.0
