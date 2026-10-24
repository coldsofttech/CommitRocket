import pytest

from commitrocket.template import DEFAULT_TEMPLATE, render_message, validate_template


def render(template, **overrides):
    values = {
        "message": "Videos ",
        "n": 22,
        "batch": 3,
        "files": 4,
        "size_mib": 123.456,
        "first": "a.mp4",
    }
    values.update(overrides)
    return render_message(template, **values)


def test_default_template_matches_the_original_format():
    assert render(DEFAULT_TEMPLATE) == "Videos #22"


def test_all_placeholders():
    text = render("{message}: {files} files, {size:.1f} MiB, {first} ({batch})")
    assert text == "Videos: 4 files, 123.5 MiB, a.mp4 (3)"


def test_date_placeholder_is_iso_date():
    assert len(render("{date}")) == 10


@pytest.mark.parametrize("template", ["{nope}", "{0}", "{n", "{n!z}"])
def test_invalid_templates_are_rejected(template):
    assert validate_template(template) is not None


def test_valid_and_empty_templates():
    assert validate_template(DEFAULT_TEMPLATE) is None
    assert validate_template("   ") is not None
