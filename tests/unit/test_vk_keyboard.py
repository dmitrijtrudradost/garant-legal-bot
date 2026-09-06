import json

from interfaces.vk.vk_interface import NEWS_KEYBOARD


def test_news_keyboard_is_valid_json_with_expected_buttons():
    data = json.loads(NEWS_KEYBOARD)

    assert data["one_time"] is False
    assert data["inline"] is False

    labels = {button["action"]["label"] for row in data["buttons"] for button in row}

    assert labels == {
        "🛡 Охрана — месяц",
        "📋 Главные новости — месяц",
        "📅 Свой период",
    }


def test_news_keyboard_has_one_button_per_row_for_mobile_readability():
    """Одна кнопка на строку — full-width текст не обрезается на маленьком экране."""
    data = json.loads(NEWS_KEYBOARD)

    for row in data["buttons"]:
        assert len(row) == 1
