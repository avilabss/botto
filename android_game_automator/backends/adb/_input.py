"""ADB input command generation and explicit humanization policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from android_game_automator.core import (
    InputAction,
    KeyPressAction,
    NormalizedPoint,
    Point,
    SwipeAction,
    TapAction,
    TextEntryAction,
    Viewport,
)

_ANDROID_KEY_CODES = frozenset(
    """
    KEYCODE_0 KEYCODE_1 KEYCODE_11 KEYCODE_12 KEYCODE_2 KEYCODE_3 KEYCODE_3D_MODE
    KEYCODE_4 KEYCODE_5 KEYCODE_6 KEYCODE_7 KEYCODE_8 KEYCODE_9 KEYCODE_A
    KEYCODE_ALL_APPS KEYCODE_ALT_LEFT KEYCODE_ALT_RIGHT KEYCODE_APOSTROPHE
    KEYCODE_APP_SWITCH KEYCODE_ASSIST KEYCODE_AT KEYCODE_AVR_INPUT KEYCODE_AVR_POWER
    KEYCODE_B KEYCODE_BACK KEYCODE_BACKSLASH KEYCODE_BOOKMARK KEYCODE_BREAK
    KEYCODE_BRIGHTNESS_DOWN KEYCODE_BRIGHTNESS_UP KEYCODE_BUTTON_1 KEYCODE_BUTTON_10
    KEYCODE_BUTTON_11 KEYCODE_BUTTON_12 KEYCODE_BUTTON_13 KEYCODE_BUTTON_14
    KEYCODE_BUTTON_15 KEYCODE_BUTTON_16 KEYCODE_BUTTON_2 KEYCODE_BUTTON_3
    KEYCODE_BUTTON_4 KEYCODE_BUTTON_5 KEYCODE_BUTTON_6 KEYCODE_BUTTON_7
    KEYCODE_BUTTON_8 KEYCODE_BUTTON_9 KEYCODE_BUTTON_A KEYCODE_BUTTON_B
    KEYCODE_BUTTON_C KEYCODE_BUTTON_L1 KEYCODE_BUTTON_L2 KEYCODE_BUTTON_MODE
    KEYCODE_BUTTON_R1 KEYCODE_BUTTON_R2 KEYCODE_BUTTON_SELECT KEYCODE_BUTTON_START
    KEYCODE_BUTTON_THUMBL KEYCODE_BUTTON_THUMBR KEYCODE_BUTTON_X KEYCODE_BUTTON_Y
    KEYCODE_BUTTON_Z KEYCODE_C KEYCODE_CALCULATOR KEYCODE_CALENDAR KEYCODE_CALL
    KEYCODE_CAMERA KEYCODE_CAPS_LOCK KEYCODE_CAPTIONS KEYCODE_CHANNEL_DOWN
    KEYCODE_CHANNEL_UP KEYCODE_CLEAR KEYCODE_CLOSE KEYCODE_COMMA KEYCODE_CONTACTS
    KEYCODE_COPY KEYCODE_CTRL_LEFT KEYCODE_CTRL_RIGHT KEYCODE_CUT KEYCODE_D
    KEYCODE_DEL KEYCODE_DEMO_APP_1 KEYCODE_DEMO_APP_2 KEYCODE_DEMO_APP_3
    KEYCODE_DEMO_APP_4 KEYCODE_DICTATE KEYCODE_DO_NOT_DISTURB KEYCODE_DPAD_CENTER
    KEYCODE_DPAD_DOWN KEYCODE_DPAD_DOWN_LEFT KEYCODE_DPAD_DOWN_RIGHT
    KEYCODE_DPAD_LEFT KEYCODE_DPAD_RIGHT KEYCODE_DPAD_UP KEYCODE_DPAD_UP_LEFT
    KEYCODE_DPAD_UP_RIGHT KEYCODE_DVR KEYCODE_E KEYCODE_EISU KEYCODE_EMOJI_PICKER
    KEYCODE_ENDCALL KEYCODE_ENTER KEYCODE_ENVELOPE KEYCODE_EQUALS KEYCODE_ESCAPE
    KEYCODE_EXPLORER KEYCODE_F KEYCODE_F1 KEYCODE_F10 KEYCODE_F11 KEYCODE_F12
    KEYCODE_F13 KEYCODE_F14 KEYCODE_F15 KEYCODE_F16 KEYCODE_F17 KEYCODE_F18
    KEYCODE_F19 KEYCODE_F2 KEYCODE_F20 KEYCODE_F21 KEYCODE_F22 KEYCODE_F23
    KEYCODE_F24 KEYCODE_F3 KEYCODE_F4 KEYCODE_F5 KEYCODE_F6 KEYCODE_F7 KEYCODE_F8
    KEYCODE_F9 KEYCODE_FEATURED_APP_1 KEYCODE_FEATURED_APP_2 KEYCODE_FEATURED_APP_3
    KEYCODE_FEATURED_APP_4 KEYCODE_FOCUS KEYCODE_FORWARD KEYCODE_FORWARD_DEL
    KEYCODE_FULLSCREEN KEYCODE_FUNCTION KEYCODE_G KEYCODE_GRAVE KEYCODE_GUIDE
    KEYCODE_H KEYCODE_HEADSETHOOK KEYCODE_HELP KEYCODE_HENKAN KEYCODE_HOME
    KEYCODE_I KEYCODE_INFO KEYCODE_INSERT KEYCODE_J KEYCODE_K KEYCODE_KANA
    KEYCODE_KATAKANA_HIRAGANA KEYCODE_KEYBOARD_BACKLIGHT_DOWN
    KEYCODE_KEYBOARD_BACKLIGHT_TOGGLE KEYCODE_KEYBOARD_BACKLIGHT_UP KEYCODE_L
    KEYCODE_LANGUAGE_SWITCH KEYCODE_LAST_CHANNEL KEYCODE_LEFT_BRACKET KEYCODE_LOCK
    KEYCODE_M KEYCODE_MACRO_1 KEYCODE_MACRO_2 KEYCODE_MACRO_3 KEYCODE_MACRO_4
    KEYCODE_MANNER_MODE KEYCODE_MEDIA_AUDIO_TRACK KEYCODE_MEDIA_CLOSE
    KEYCODE_MEDIA_EJECT KEYCODE_MEDIA_FAST_FORWARD KEYCODE_MEDIA_NEXT
    KEYCODE_MEDIA_PAUSE KEYCODE_MEDIA_PLAY KEYCODE_MEDIA_PLAY_PAUSE
    KEYCODE_MEDIA_PREVIOUS KEYCODE_MEDIA_RECORD KEYCODE_MEDIA_REWIND
    KEYCODE_MEDIA_SKIP_BACKWARD KEYCODE_MEDIA_SKIP_FORWARD KEYCODE_MEDIA_STEP_BACKWARD
    KEYCODE_MEDIA_STEP_FORWARD KEYCODE_MEDIA_STOP KEYCODE_MEDIA_TOP_MENU KEYCODE_MENU
    KEYCODE_META_LEFT KEYCODE_META_RIGHT KEYCODE_MINUS KEYCODE_MOVE_END
    KEYCODE_MOVE_HOME KEYCODE_MUHENKAN KEYCODE_MUSIC KEYCODE_MUTE KEYCODE_N
    KEYCODE_NAVIGATE_IN KEYCODE_NAVIGATE_NEXT KEYCODE_NAVIGATE_OUT
    KEYCODE_NAVIGATE_PREVIOUS KEYCODE_NEW KEYCODE_NOTIFICATION KEYCODE_NUM
    KEYCODE_NUM_LOCK KEYCODE_NUMPAD_0 KEYCODE_NUMPAD_1 KEYCODE_NUMPAD_2
    KEYCODE_NUMPAD_3 KEYCODE_NUMPAD_4 KEYCODE_NUMPAD_5 KEYCODE_NUMPAD_6
    KEYCODE_NUMPAD_7 KEYCODE_NUMPAD_8 KEYCODE_NUMPAD_9 KEYCODE_NUMPAD_ADD
    KEYCODE_NUMPAD_COMMA KEYCODE_NUMPAD_DIVIDE KEYCODE_NUMPAD_DOT
    KEYCODE_NUMPAD_ENTER KEYCODE_NUMPAD_EQUALS KEYCODE_NUMPAD_LEFT_PAREN
    KEYCODE_NUMPAD_MULTIPLY KEYCODE_NUMPAD_RIGHT_PAREN KEYCODE_NUMPAD_SUBTRACT
    KEYCODE_O KEYCODE_P KEYCODE_PAGE_DOWN KEYCODE_PAGE_UP KEYCODE_PAIRING
    KEYCODE_PASTE KEYCODE_PERIOD KEYCODE_PICTSYMBOLS KEYCODE_PLUS KEYCODE_POUND
    KEYCODE_POWER KEYCODE_PRINT KEYCODE_PROFILE_SWITCH KEYCODE_PROG_BLUE
    KEYCODE_PROG_GREEN KEYCODE_PROG_RED KEYCODE_PROG_YELLOW KEYCODE_Q KEYCODE_R
    KEYCODE_RECENT_APPS KEYCODE_REFRESH KEYCODE_RIGHT_BRACKET KEYCODE_RO KEYCODE_S
    KEYCODE_SCREENSHOT KEYCODE_SCROLL_LOCK KEYCODE_SEARCH KEYCODE_SEMICOLON
    KEYCODE_SETTINGS KEYCODE_SHIFT_LEFT KEYCODE_SHIFT_RIGHT KEYCODE_SLASH
    KEYCODE_SLEEP KEYCODE_SOFT_LEFT KEYCODE_SOFT_RIGHT KEYCODE_SOFT_SLEEP
    KEYCODE_SPACE KEYCODE_STAR KEYCODE_STB_INPUT KEYCODE_STB_POWER KEYCODE_STEM_1
    KEYCODE_STEM_2 KEYCODE_STEM_3 KEYCODE_STEM_PRIMARY KEYCODE_STYLUS_BUTTON_PRIMARY
    KEYCODE_STYLUS_BUTTON_SECONDARY KEYCODE_STYLUS_BUTTON_TAIL
    KEYCODE_STYLUS_BUTTON_TERTIARY KEYCODE_SWITCH_CHARSET KEYCODE_SYM KEYCODE_SYSRQ
    KEYCODE_SYSTEM_NAVIGATION_DOWN KEYCODE_SYSTEM_NAVIGATION_LEFT
    KEYCODE_SYSTEM_NAVIGATION_RIGHT KEYCODE_SYSTEM_NAVIGATION_UP KEYCODE_T
    KEYCODE_TAB KEYCODE_THUMBS_DOWN KEYCODE_THUMBS_UP KEYCODE_TV
    KEYCODE_TV_ANTENNA_CABLE KEYCODE_TV_AUDIO_DESCRIPTION
    KEYCODE_TV_AUDIO_DESCRIPTION_MIX_DOWN KEYCODE_TV_AUDIO_DESCRIPTION_MIX_UP
    KEYCODE_TV_CONTENTS_MENU KEYCODE_TV_DATA_SERVICE KEYCODE_TV_INPUT
    KEYCODE_TV_INPUT_COMPONENT_1 KEYCODE_TV_INPUT_COMPONENT_2
    KEYCODE_TV_INPUT_COMPOSITE_1 KEYCODE_TV_INPUT_COMPOSITE_2
    KEYCODE_TV_INPUT_HDMI_1 KEYCODE_TV_INPUT_HDMI_2 KEYCODE_TV_INPUT_HDMI_3
    KEYCODE_TV_INPUT_HDMI_4 KEYCODE_TV_INPUT_VGA_1 KEYCODE_TV_MEDIA_CONTEXT_MENU
    KEYCODE_TV_NETWORK KEYCODE_TV_NUMBER_ENTRY KEYCODE_TV_POWER
    KEYCODE_TV_RADIO_SERVICE KEYCODE_TV_SATELLITE KEYCODE_TV_SATELLITE_BS
    KEYCODE_TV_SATELLITE_CS KEYCODE_TV_SATELLITE_SERVICE KEYCODE_TV_TELETEXT
    KEYCODE_TV_TERRESTRIAL_ANALOG KEYCODE_TV_TERRESTRIAL_DIGITAL
    KEYCODE_TV_TIMER_PROGRAMMING KEYCODE_TV_ZOOM_MODE KEYCODE_U KEYCODE_UNKNOWN
    KEYCODE_V KEYCODE_VIDEO_APP_1 KEYCODE_VIDEO_APP_2 KEYCODE_VIDEO_APP_3
    KEYCODE_VIDEO_APP_4 KEYCODE_VIDEO_APP_5 KEYCODE_VIDEO_APP_6 KEYCODE_VIDEO_APP_7
    KEYCODE_VIDEO_APP_8 KEYCODE_VOICE_ASSIST KEYCODE_VOLUME_DOWN
    KEYCODE_VOLUME_MUTE KEYCODE_VOLUME_UP KEYCODE_W KEYCODE_WAKEUP KEYCODE_WINDOW
    KEYCODE_X KEYCODE_Y KEYCODE_YEN KEYCODE_Z KEYCODE_ZENKAKU_HANKAKU
    KEYCODE_ZOOM_IN KEYCODE_ZOOM_OUT
    """.split()
)


@dataclass(frozen=True, slots=True)
class AdbCoordinateOffset:
    """Signed pixel offset applied by the humanization policy."""

    x: int = 0
    y: int = 0


@dataclass(frozen=True, slots=True)
class AdbInputHumanizationPolicy:
    """Small deterministic adjustments for ADB input execution."""

    coordinate_offset_px: AdbCoordinateOffset = field(default_factory=AdbCoordinateOffset)
    duration_scale: float = 1.0
    duration_offset_ms: int = 0

    def __post_init__(self) -> None:
        if self.duration_scale <= 0:
            raise ValueError("duration_scale must be > 0")

    def adjust_point(self, point: Point, viewport: Viewport | None = None) -> Point:
        """Apply a fixed offset and clamp when a target viewport is available."""
        x = max(point.x + self.coordinate_offset_px.x, 0)
        y = max(point.y + self.coordinate_offset_px.y, 0)

        if viewport is not None:
            region = viewport.region
            if region is None:
                raise RuntimeError("viewport region was not initialized")

            x = min(max(x, region.left), region.right - 1)
            y = min(max(y, region.top), region.bottom - 1)

        return Point(x=x, y=y)

    def adjust_hold_ms(self, duration_ms: int) -> int:
        """Adjust a tap-hold duration while preserving zero-duration taps."""
        if duration_ms <= 0:
            return 0
        return max(
            1,
            _scaled_duration_ms(duration_ms, self.duration_scale, self.duration_offset_ms),
        )

    def adjust_swipe_duration_ms(self, duration_ms: int) -> int:
        """Adjust a swipe duration while keeping it strictly positive."""
        return max(
            1,
            _scaled_duration_ms(duration_ms, self.duration_scale, self.duration_offset_ms),
        )


@dataclass(frozen=True, slots=True)
class AdbInputCommand:
    """A generated adb shell command for a single input action."""

    shell_command: str
    rejection_message: str | None = None


def build_adb_input_command(
    action: InputAction,
    viewport: Viewport | None = None,
    humanization: AdbInputHumanizationPolicy | None = None,
) -> AdbInputCommand:
    """Build an adb shell input command for a core input action."""
    policy = humanization if humanization is not None else AdbInputHumanizationPolicy()

    if isinstance(action, TapAction):
        point = _resolve_point(action.point, viewport, policy, action_name="tap")
        hold_ms = policy.adjust_hold_ms(action.hold_ms)
        if hold_ms > 0:
            return AdbInputCommand(
                shell_command=(
                    f"input swipe {point.x} {point.y} {point.x} {point.y} {hold_ms}"
                )
            )
        return AdbInputCommand(shell_command=f"input tap {point.x} {point.y}")

    if isinstance(action, SwipeAction):
        start = _resolve_point(action.start, viewport, policy, action_name="swipe")
        end = _resolve_point(action.end, viewport, policy, action_name="swipe")
        duration_ms = policy.adjust_swipe_duration_ms(action.duration_ms)
        return AdbInputCommand(
            shell_command=(
                f"input swipe {start.x} {start.y} {end.x} {end.y} {duration_ms}"
            )
        )

    if isinstance(action, KeyPressAction):
        key_code = _normalize_key_code(action.key)
        if key_code is None:
            return AdbInputCommand(
                shell_command="",
                rejection_message=f"Unsupported Android key identifier: {action.key!r}.",
            )
        return AdbInputCommand(shell_command=f"input keyevent {key_code}")

    if isinstance(action, TextEntryAction):
        if _text_requires_unrepresentable_adb_escape(action.text):
            return AdbInputCommand(
                shell_command="",
                rejection_message=(
                    "Text contains a literal '%s' sequence that plain adb input text "
                    "cannot represent faithfully."
                ),
            )
        return AdbInputCommand(
            shell_command=f"input text {_quote_shell_arg(_encode_adb_text(action.text))}"
        )

    raise TypeError(f"Unsupported input action type: {type(action)!r}")


def _require_viewport(viewport: Viewport | None, action_name: str) -> Viewport:
    if viewport is None:
        raise ValueError(f"viewport is required for {action_name} actions")
    return viewport


def _resolve_point(
    point: Point | NormalizedPoint,
    viewport: Viewport | None,
    humanization: AdbInputHumanizationPolicy,
    action_name: str,
) -> Point:
    if isinstance(point, NormalizedPoint):
        resolved = _require_viewport(viewport, action_name=action_name).map_point(point)
    else:
        resolved = point
    return humanization.adjust_point(resolved, viewport)


def _normalize_key_code(key: str) -> str | None:
    normalized = key.strip().upper()
    if not normalized:
        return None
    if normalized.isdigit():
        return normalized

    candidate = normalized if normalized.startswith("KEYCODE_") else f"KEYCODE_{normalized}"
    if not all(char.isalnum() or char == "_" for char in candidate):
        return None
    if candidate not in _ANDROID_KEY_CODES:
        return None
    return candidate


def _encode_adb_text(text: str) -> str:
    return text.replace(" ", "%s")


def _text_requires_unrepresentable_adb_escape(text: str) -> bool:
    return "%s" in text


def _quote_shell_arg(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _scaled_duration_ms(duration_ms: int, scale: float, offset_ms: int) -> int:
    scaled = (Decimal(duration_ms) * Decimal(repr(scale))) + Decimal(offset_ms)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))
