from nllb_api.segmentation import split_sentences


def test_splits_on_sentence_end_followed_by_space() -> None:
    assert split_sentences("Hola. ¿Qué tal? ¡Bien! Vale…  Ok", 400) == [
        "Hola.",
        "¿Qué tal?",
        "¡Bien!",
        "Vale…",
        "Ok",
    ]


def test_does_not_split_decimals_or_urls() -> None:
    text = "El precio es 3.5 euros en https://bit2me.com/es."
    assert split_sentences(text, 400) == [text]


def test_blank_line_has_no_sentences() -> None:
    assert split_sentences("   ", 400) == []


def test_long_sentence_is_wrapped_on_word_boundaries() -> None:
    sentence = " ".join(["palabra"] * 30)
    chunks = split_sentences(sentence, 50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert " ".join(chunks) == sentence


def test_oversized_word_is_cut_by_characters() -> None:
    assert split_sentences("a " + "x" * 45, 20) == ["a", "x" * 20, "x" * 20, "x" * 5]


def test_text_without_spaces_never_exceeds_the_limit() -> None:
    chunks = split_sentences("y" * 50_000, 400)
    assert max(map(len, chunks)) == 400
    assert "".join(chunks) == "y" * 50_000


def test_oversized_word_in_the_middle_keeps_its_neighbours() -> None:
    assert split_sentences("ver " + "z" * 25 + " ahora", 20) == ["ver", "z" * 20, "zzzzz ahora"]


def test_multiletter_dotted_acronyms_do_not_end_the_sentence() -> None:
    assert split_sentences("Viven en EE.UU. desde 2010. Les gusta.", 400) == [
        "Viven en EE.UU. desde 2010.",
        "Les gusta.",
    ]


def test_does_not_split_after_spanish_abbreviations() -> None:
    text = "El Sr. García vive en EE. UU. desde 2020."
    assert split_sentences(text, 400) == [text]
    assert split_sentences("Hay opciones, p. ej. comprar o vender.", 400) == [
        "Hay opciones, p. ej. comprar o vender."
    ]


def test_does_not_split_after_initials_and_dotted_acronyms() -> None:
    text = "J. R. R. Tolkien escribió para Acme S.A. en Madrid."
    assert split_sentences(text, 400) == [text]


def test_list_markers_stay_with_their_item() -> None:
    assert split_sentences("1. Comprar bitcoin. 2) Guardarlo. 3. Esperar", 400) == [
        "1. Comprar bitcoin.",
        "2) Guardarlo.",
        "3. Esperar",
    ]


def test_real_sentence_boundaries_survive_the_merging() -> None:
    assert split_sentences("Compré en 2024. Luego vendí. ¿Y ahora?", 400) == [
        "Compré en 2024.",
        "Luego vendí.",
        "¿Y ahora?",
    ]


def test_trailing_abbreviation_is_kept() -> None:
    assert split_sentences("Hola. Habla con el Dr.", 400) == ["Hola.", "Habla con el Dr."]
