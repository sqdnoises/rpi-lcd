from dataclasses import dataclass
from typing import List, Literal, Tuple
from smbus import SMBus  # type: ignore
from time import sleep
import time

__all__ = (
    "ScrollLine",
    "LCD",
)

RS_BIT = 0b00000001
RW_BIT = 0b00000010
ENABLE_BIT = 0b00000100
LCD_BACKLIGHT = 0b00001000
LCD_NOBACKLIGHT = 0b00000000

CLEAR_DISPLAY = 0x01  # Clears display, sets cursor to home
RETURN_HOME = 0x02  # Sets cursor to home, does not clear display
ENTRY_MODE_SET = 0x04  # Sets cursor move direction and display shift
DISPLAY_CONTROL = 0x08  # Controls display, cursor, and blink
CURSOR_SHIFT = 0x10  # Moves cursor or shifts display
FUNCTION_SET = 0x20  # Sets interface data length, number of lines, and font
SET_CGRAM_ADDR = 0x40  # Sets Character Generator RAM address
SET_DDRAM_ADDR = 0x80  # Sets Display Data RAM address (cursor position)

# FUNCTION_SET Options:
# DL: Data Length (1=8bit, 0=4bit)
# N: Number of Lines (0=1 line, 1=2 lines - often interpreted as 2 lines even for 4 line displays for base addressing)
# F: Font Type (0=5x8 dots, 1=5x10 dots)
LCD_FUNCTION_SET_4BIT_2LINE_5X8 = (
    FUNCTION_SET | 0x00 | 0x08 | 0x00
)  # 0b00101000 (DL=0, N=1, F=0)

# ENTRY_MODE_SET Options:
# ID: Increment/Decrement cursor (1=Increment, 0=Decrement)
# S: Display Shift (1=Shift display, 0=Don't shift)
LCD_ENTRY_MODE_INCREMENT_NO_SHIFT = (
    ENTRY_MODE_SET | 0x02 | 0x00
)  # 0b00000110 (ID=1, S=0)

# DISPLAY_CONTROL Options:
# D: Display ON/OFF (1=ON, 0=OFF)
# C: Cursor ON/OFF (1=ON, 0=OFF)
# B: Blinking ON/OFF (1=ON, 0=OFF)
LCD_DISPLAY_ON_NO_CURSOR_NO_BLINK = (
    DISPLAY_CONTROL | 0x04 | 0x00 | 0x00
)  # 0b00001100 (D=1, C=0, B=0)
LCD_DISPLAY_ON_CURSOR_ON_NO_BLINK = (
    DISPLAY_CONTROL | 0x04 | 0x02 | 0x00
)  # 0b00001110 (D=1, C=1, B=0)
LCD_DISPLAY_ON_NO_CURSOR_BLINK_ON = (
    DISPLAY_CONTROL | 0x04 | 0x00 | 0x01
)  # 0b00001101 (D=1, C=0, B=1)
LCD_DISPLAY_ON_CURSOR_ON_BLINK_ON = (
    DISPLAY_CONTROL | 0x04 | 0x02 | 0x01
)  # 0b00001111 (D=1, C=1, B=1)


LCD_INIT_4BIT_PART1 = 0x33
LCD_INIT_4BIT_PART2 = 0x32


LINES: dict[int, int] = {
    1: 0x80,  # Address for line 1
    2: 0xC0,  # Address for line 2
    3: 0x94,  # Address for line 3 (for 4-line displays)
    4: 0xD4,  # Address for line 4 (for 4-line displays)
}

ALIGN_FUNC: dict[str, str] = {
    "left": "ljust",
    "right": "rjust",
    "center": "center",
}


@dataclass
class ScrollLine:
    """
    Configuration for a single line within the animated_display function.
    """

    text: str
    line: int

    # Delay between character shifts during scrolling
    scroll_delay: float = 0.2

    # Delay before the scrolling animation starts (after initial display)
    start_delay: float = 0.5

    # Delay between scrolling phases (e.g., left then right)
    phase_delay: float = 0.5

    # Delay after a full scroll loop completes
    end_delay: float = 0.5

    # Scrolling direction
    direction: Literal["left", "right", "both_lr", "both_rl"] = "left"

    # Number of times to repeat the scroll animation cycle. 0 for infinite.
    loops: int = 1

    # Maximum duration (in seconds) for the animation. 0 for no timeout.
    timeout: float = 0


class LCD:
    """
    Represents an I2C LCD display controlled via an HD44780 compatible chip
    and an I2C expander like the PCF8574.
    """

    address: int
    bus: SMBus
    delay: float
    rows: int
    width: int
    _backlight: bool

    def __init__(
        self,
        address: int = 0x27,
        bus: int = 1,
        width: int = 16,
        rows: int = 2,
        backlight: bool = True,
        clear_on_init: bool = True,
    ) -> None:
        """
        Initializes the I2C LCD display.

        Args:
            address (int): The I2C address of the LCD backpack (default is 0x27, common).
            bus (int): The I SMBus channel number (default is 1, common for Raspberry Pi).
            width (int): The number of columns on the display (e.g., 16 or 20). Defaults to 16.
            rows (int): The number of rows on the display (e.g., 2 or 4). Defaults to 2.
            backlight (bool): Initial state of the backlight (True for ON, False for OFF). Defaults to True.
            clear_on_init (bool): If True, clears the display on initialization. Defaults to True.
        """
        self.address = address
        self.bus = SMBus(bus)
        # Short delay needed between I2C writes for the LCD controller
        self.delay = 0.0005
        self.rows = rows
        self.width = width
        self._backlight = backlight

        # Initialize display to 4-bit mode
        # This sequence is specific and required for reliable initialization
        self.write(LCD_INIT_4BIT_PART1)  # Send 0x30/0x33 three times (part 1)
        self.write(
            LCD_INIT_4BIT_PART2  # Send 0x32/0x33 (part 2, actual switch to 4-bit)
        )

        # Configure display settings (now in 4-bit mode)
        # DL=0 (4-bit mode), N=1 (2 lines), F=0 (5x8 font)
        self.write(LCD_FUNCTION_SET_4BIT_2LINE_5X8)
        # ID=1 (Increment cursor), S=0 (No display shift)
        self.write(LCD_ENTRY_MODE_INCREMENT_NO_SHIFT)
        # D=1 (Display ON), C=0 (Cursor OFF), B=0 (Blink OFF)
        self.write(LCD_DISPLAY_ON_NO_CURSOR_NO_BLINK)

        if clear_on_init:
            self.clear()

    @property
    def backlight(self) -> bool:
        """Gets the current backlight status."""
        return self._backlight

    @backlight.setter
    def backlight(self, value: bool) -> None:
        """Sets the backlight status and updates the display."""
        self._backlight = value
        # Need to resend a command/data to update the backlight state on the PCF8574
        # The easiest way is to just send a dummy command or the current display control
        # Without sending *something*, the PCF8574 output pins don't change state.
        # Resending the display control command is simple and safe.
        self.write(LCD_DISPLAY_ON_NO_CURSOR_NO_BLINK)

    def _write_byte(self, byte: int) -> None:
        """
        Sends a byte to the I2C expander, performing the Enable pulse.

        This method takes an 8-bit value representing the state of the
        PCF8574 output pins (4 LCD data bits + RS + RW + Enable + Backlight)
        and pulses the LCD's Enable pin to latch the data.

        Args:
            byte (int): The 8-bit value to write to the PCF8574 I2C port.
        """
        # RS, RW, Data, Backlight are set. Enable is LOW.
        self.bus.write_byte(self.address, byte)
        # Set Enable HIGH to latch data/command
        self.bus.write_byte(self.address, (byte | ENABLE_BIT))
        sleep(self.delay)  # Short pulse time
        # Set Enable LOW to complete the cycle
        self.bus.write_byte(self.address, (byte & ~ENABLE_BIT))
        sleep(self.delay)  # Wait for LCD internal operations

    def write(self, byte: int, mode: int = 0) -> None:
        """
        Sends an 8-bit command or data byte to the LCD controller using the 4-bit interface.

        This method splits the 8-bit byte into two 4-bit nibbles (high then low),
        combines each nibble with control bits (RS, Backlight), and sends
        the resulting 8-bit payloads to the `_write_byte` method for strobing.

        Args:
            byte (int): The 8-bit command or data byte to send.
            mode (int): The Register Select (RS) bit value.
                  0 for command (RS low), 1 for data (RS high). Defaults to 0 (command).
        """
        # Get the current backlight state bit
        backlight_mode: int = LCD_BACKLIGHT if self.backlight else LCD_NOBACKLIGHT

        # Send the high nibble
        # The data bits must be in the upper 4 bits (D7-D4) of the byte sent to _write_byte
        high_nibble: int = byte & 0xF0  # Extract bits 7-4
        self._write_byte(mode | high_nibble | backlight_mode)

        # Send the low nibble
        # Shift bits 3-0 to positions 7-4
        low_nibble: int = (byte << 4) & 0xF0  # Extract bits 3-0 and shift left
        self._write_byte(mode | low_nibble | backlight_mode)

    def text(
        self,
        text: str,
        line: int = 1,
        align: Literal["left", "right", "center"] = "left",
    ) -> None:
        """
        Writes text to a specific line on the LCD, with optional wrapping and alignment.

        Args:
            text (str): The string of text to display.
            line (int): The line number (1-based) to start writing on. Defaults to 1.
            align (Literal["left", "right", "center"]): The horizontal alignment for the text within the line space
                   ('left', 'right', or 'center'). Defaults to 'left'.
        """
        # Set cursor to the start of the requested line
        line_address: int = LINES.get(line, LINES[1])  # Default to line 1 if invalid
        self.write(SET_DDRAM_ADDR | line_address)

        # Handle potential line wrapping
        current_line_text, remaining_text = self.get_text_line(text)

        # Apply alignment and pad with spaces to fill the line width
        # This overwrites existing characters on the line.
        aligned_text: str = getattr(current_line_text, ALIGN_FUNC.get(align, "ljust"))(
            self.width
        )

        # Send each character of the aligned text as data
        for char in aligned_text:
            self.write(ord(char), mode=1)  # mode=1 sends character data

        # Recursively display the remaining text on the next line if available
        if remaining_text and line < self.rows:
            # Move to the next line and call text again with the remaining part
            self.text(remaining_text, line + 1, align=align)

    def get_text_line(self, text: str) -> Tuple[str, str]:
        """
        Splits a text string into a portion that fits on one line and any remaining text.

        Attempts to break at a space if the text exceeds the line width to avoid
        splitting words.

        Args:
            text (str): The input string.

        Returns:
            A tuple containing:
            - The portion of the text for the current line.
            - The remaining text after the break, with leading/trailing whitespace stripped.
        """
        # If text fits within the width, return it as the only line
        if len(text) <= self.width:
            return text, ""

        # Find the last space within the first (width + 1) characters
        # Adding +1 allows checking just beyond the width to find a break point
        possible_break_point: int = text[: self.width + 1].rfind(" ")

        # Determine the actual line break position
        if possible_break_point < 0 or possible_break_point > self.width:
            # No space found within the potential range, or space is just beyond width.
            # Break strictly at the width limit.
            line_break: int = self.width
        else:
            # Break at the last space found within the limit
            line_break = possible_break_point

        # Split the text
        line_text: str = text[:line_break]
        remaining_text: str = text[
            line_break:
        ].strip()  # Strip leading/trailing whitespace from remaining

        return line_text, remaining_text

    def clear(self) -> None:
        """
        Clears the display content and returns the cursor to the home position (top-left).
        """
        self.write(CLEAR_DISPLAY)
        sleep(
            self.delay * 2
        )  # Clearing the display takes longer, add a slightly longer delay

    def clear_line(self, line: int) -> None:
        """Clears the content of a specific line on the display.

        Args:
            line (int): The line number to clear.
        """
        line_address: int | None = LINES.get(line)
        if line_address is None or line > self.rows:
            print(
                f"Warning: Invalid line number {line} for {self.rows}-row display. Cannot clear line."
            )
            return

        # Set cursor to the start of the line
        self.write(SET_DDRAM_ADDR | line_address)
        # Write spaces to overwrite existing characters on the line
        for _ in range(self.width):
            self.write(ord(" "), mode=1)
        # Return cursor to the start of the line after clearing
        self.write(SET_DDRAM_ADDR | line_address)

    def scroll_text(
        self,
        text: str,
        line: int = 1,
        scroll_delay: float = 0.2,
        *,
        start_delay: float = 0.5,
        phase_delay: float = 0.5,
        end_delay: float = 0.5,
        direction: Literal["left", "right", "both_lr", "both_rl"] = "left",
        loops: int = 1,  # 0 for infinite
        timeout: float = 0,  # 0 for no timeout
    ) -> None:
        """
        Scrolls text across a specific line if it's longer than the display width.

        If the text is shorter than or equal to the display width, it will be
        displayed statically, left-aligned, without scrolling.

        Args:
            text (str): The string of text to display and scroll.
            line (int): The line number (1-based) on which to scroll. Defaults to 1.
            scroll_delay (float): The delay (in seconds) between each character shift. Defaults to 0.2.
            start_delay (float): The delay (in seconds) before starting the scroll animation.
                          This allows the user to prepare for the scrolling effect.
                          Defaults to 0.5.
            phase_delay (float): The delay (in seconds) between different phases of the scroll.
                         This is used when scrolling in both directions (left and right).
                         This allows the user to see the text before it starts scrolling back.
                         Defaults to 0.5.
            end_delay (float): The delay (in seconds) after completing a full scroll cycle.
                        This allows the user to see the final position before the next cycle starts.
                        Defaults to 0.5.
            direction (Literal["left", "right", "both_lr", "both_rl"]): The scrolling direction.
                       "left": Scrolls from start to end (leftwards).
                       "right": Scrolls from end to start (rightwards).
                       "both_lr": Scrolls left, then right back to the start.
                       "both_rl": Scrolls right (from left edge view), then left back to the end view.
                       Defaults to "left".
            loops (int): The number of times to repeat the full scroll animation cycle.
                   Use 0 for infinite looping until timeout or interruption. Defaults to 1.
            timeout (float): The maximum duration (in seconds) for the scrolling animation.
                     If the timeout is reached, the scrolling stops, overriding 'loops'.
                     Use 0 for no timeout. Defaults to 0.
        """
        # Validate direction input
        valid_directions = ["left", "right", "both_lr", "both_rl"]
        if direction not in valid_directions:
            print(f"Warning: Invalid scroll direction '{direction}'. Using 'left'.")
            direction = "left"

        # Get line address and validate line number
        # Return silently if the line is invalid
        line_address: int | None = LINES.get(line)
        if line_address is None or line > self.rows:
            print(
                f"Warning: Invalid line number {line} for {self.rows}-row display. Cannot scroll."
            )
            return

        # If text is shorter or equal to the width, just display it and return
        if len(text) <= self.width:
            self.text(text, line)
            return

        # Text is longer than width, prepare for scrolling
        # num_shifts is the number of times we need to shift to see the whole text
        num_shifts = len(text) - self.width

        # Set up timeout
        end_time = time.monotonic() + timeout if timeout > 0 else float("inf")

        # Clear the target line before starting
        self.clear_line(line)

        # Scrolling Animation Loop
        current_loops = 0
        while loops == 0 or current_loops < loops:  # loops=0 means infinite
            if time.monotonic() > end_time:
                break  # Timeout occurred

            # Define the phases for the current loop iteration
            # Each phase is a sequence of displaying visible windows of the text
            phases = []
            if direction == "left":
                # Indices 0, 1, ..., num_shifts (inclusive)
                phases = [range(num_shifts + 1)]
            elif direction == "right":
                # Indices num_shifts, num_shifts-1, ..., 0 (inclusive)
                phases = [range(num_shifts, -1, -1)]
            elif direction == "both_lr":
                # Phase 1 (Left): 0 to num_shifts
                # Phase 2 (Right): num_shifts-1 down to 0 (avoid repeating the last view)
                phases = [range(num_shifts + 1), range(num_shifts - 1, -1, -1)]
            elif direction == "both_rl":
                # Phase 1 (Right): num_shifts down to 0
                # Phase 2 (Left): 1 to num_shifts (avoid repeating the last view)
                phases = [range(num_shifts, -1, -1), range(1, num_shifts + 1)]

            first_phase_incdice = True

            # Execute phases
            for phase_no, phase_indices in enumerate(phases, start=1):
                if time.monotonic() > end_time:
                    break  # Timeout occurred

                for i in phase_indices:
                    if time.monotonic() > end_time:
                        break  # Timeout occurred during shifts

                    # Get the visible portion of the text for the current scroll index i
                    visible_text_slice = text[i : i + self.width]

                    # Use self.text to display this slice on the line.
                    # self.text handles setting cursor to the line and padding with spaces.
                    self.text(visible_text_slice, line)

                    if first_phase_incdice:
                        # If this is the first phase indice, wait for the start delay before scrolling
                        sleep(start_delay)
                        first_phase_incdice = False

                    # Wait before the next shift
                    sleep(scroll_delay)

                if len(phases) > 1 and phase_no < len(phases):
                    # If there are multiple phases, wait for the phase delay after each phase
                    # except the last one
                    sleep(phase_delay)

            # After completing the phase, wait for the end delay
            sleep(end_delay)

            # End of phases for the current loop iteration
            if time.monotonic() > end_time:
                break  # Timeout occurred

            current_loops += 1
            if loops != 0 and current_loops >= loops:
                break  # Finished required loops (and not infinite)

        # After scrolling finishes (loops complete or timeout):
        # Display the beginning of the text left-aligned on the line.
        # This makes sure a predictable final state.
        # Only reset if not interrupted by timeout *exactly* at the end of a loop/phase
        # (Checking end_time again is redundant due to checks inside loops, but safe)
        if time.monotonic() <= end_time:
            self.text(text[: self.width], line)

    def animated_display(self, lines: List[ScrollLine]) -> None:
        """
        Displays and animates multiple lines on the LCD simultaneously
        based on the configurations provided in a list of ScrollLine objects.
        """
        line_states = {}
        now = time.monotonic()
        overall_end_time = float("inf")  # Tracks the earliest timeout across all lines

        # Initialize state for each configured line
        for config in lines:
            if config.line not in LINES or config.line > self.rows:
                print(
                    f"Warning: Invalid line number {config.line} for {self.rows}-row display. Skipping."
                )
                continue
            self.clear_line(config.line)

            all_phases_indices: List[List[int]] = []
            num_shifts = 0

            # Handle static text: display and mark as finished
            if len(config.text) <= self.width:
                self.text(config.text, config.line)
                line_states[config.line] = {
                    "config": config,
                    "state": "finished",
                    "next_action_time": float("inf"),
                    "all_phases_indices": all_phases_indices,
                }
                continue

            # Setup for scrolling text
            num_shifts = len(config.text) - self.width
            end_time = now + config.timeout if config.timeout > 0 else float("inf")
            overall_end_time = min(overall_end_time, end_time)

            # Calculate scroll phase sequences based on direction
            valid_directions = ["left", "right", "both_lr", "both_rl"]
            actual_direction = (
                config.direction if config.direction in valid_directions else "left"
            )
            if actual_direction == "left":
                all_phases_indices = [list(range(num_shifts + 1))]
            elif actual_direction == "right":
                all_phases_indices = [list(range(num_shifts, -1, -1))]
            elif actual_direction == "both_lr":
                all_phases_indices = [
                    list(range(num_shifts + 1)),
                    list(range(num_shifts - 1, -1, -1)),
                ]
            elif actual_direction == "both_rl":
                all_phases_indices = [
                    list(range(num_shifts, -1, -1)),
                    list(range(1, num_shifts + 1)),
                ]

            # Find the first non-empty phase sequence
            first_phase_index = 0
            while (
                first_phase_index < len(all_phases_indices)
                and not all_phases_indices[first_phase_index]
            ):
                first_phase_index += 1

            if (
                first_phase_index >= len(all_phases_indices)
                or not all_phases_indices[first_phase_index]
            ):
                print(
                    f"Error: No scrollable phases for '{config.text}' on line {config.line}. Finished."
                )
                self.text(config.text[: self.width], config.line)
                line_states[config.line] = {
                    "config": config,
                    "state": "finished",
                    "next_action_time": float("inf"),
                    "all_phases_indices": all_phases_indices,
                }
                continue

            # Display initial frame of scrolling text
            initial_phase_indices = all_phases_indices[first_phase_index]
            initial_text_index = initial_phase_indices[0]
            initial_slice = config.text[
                initial_text_index : initial_text_index + self.width
            ]
            self.text(initial_slice, config.line)

            # Store initial state for scrolling line
            line_states[config.line] = {
                "config": config,
                "state": "awaiting_first_scroll",
                "next_action_time": now + config.start_delay,
                "current_loop": 0,  # Loops start at 0, increment *after* a loop completes
                "current_phase_idx": first_phase_index,
                "current_frame_in_phase_idx": 1,  # Next frame to display is index 1 (frame 0 already shown)
                "all_phases_indices": all_phases_indices,
                "end_time": end_time,
            }

        # Main animation loop: process lines until all are finished
        active_line_numbers = [
            ln for ln, state in line_states.items() if state["state"] != "finished"
        ]
        while active_line_numbers:
            now = time.monotonic()

            # Handle overall animation timeout
            if now >= overall_end_time:
                for line_num in list(active_line_numbers):  # Iterate copy
                    state = line_states[line_num]
                    if len(state["config"].text) > self.width:  # If it was scrolling
                        self.text(state["config"].text[: self.width], line_num)
                    state["state"] = "finished"
                    state["next_action_time"] = float("inf")
                    active_line_numbers.remove(line_num)
                break  # Exit main animation loop

            if not active_line_numbers:  # All lines might have finished
                break

            # Efficiently wait until the next action is due
            min_next_action_time = min(
                line_states[ln]["next_action_time"] for ln in active_line_numbers
            )
            if now < min_next_action_time:
                sleep_duration = min_next_action_time - now
                sleep_amount = (
                    max(0.001, sleep_duration) if sleep_duration > 0 else 0.001
                )
                sleep(sleep_amount)
                now = time.monotonic()

            # Process lines whose action time has arrived
            for line_num in list(active_line_numbers):  # Iterate copy
                state = line_states[line_num]

                if state["state"] == "finished" or now < state["next_action_time"]:
                    continue

                # Handle individual line timeout (takes precedence)
                if now >= state["end_time"]:
                    if len(state["config"].text) > self.width:  # If it was scrolling
                        self.text(state["config"].text[: self.width], line_num)
                    state["state"] = "finished"
                    state["next_action_time"] = float("inf")
                    active_line_numbers.remove(line_num)
                    continue

                config = state["config"]

                # State: Initial start_delay is over (or start_delay for a new loop)
                if state["state"] == "awaiting_first_scroll":
                    state["state"] = "scrolling"
                    # current_frame_in_phase_idx is already set for the first frame to scroll (index 1, or 0 for subsequent loops)
                    # The actual display of this frame happens when 'scrolling' state is processed *now*.
                    state["next_action_time"] = (
                        now  # Process scrolling action immediately
                    )

                # State: Display current scroll frame
                elif state["state"] == "scrolling":
                    current_phase_indices = state["all_phases_indices"][
                        state["current_phase_idx"]
                    ]
                    frame_to_display_idx = state["current_frame_in_phase_idx"]

                    if frame_to_display_idx < len(current_phase_indices):
                        # Display current frame
                        actual_text_start_index = current_phase_indices[
                            frame_to_display_idx
                        ]
                        visible_text_slice = config.text[
                            actual_text_start_index : actual_text_start_index
                            + self.width
                        ]
                        self.text(visible_text_slice, line_num)
                        state[
                            "current_frame_in_phase_idx"
                        ] += 1  # Advance to next frame

                        # Determine next step after displaying frame
                        if state["current_frame_in_phase_idx"] < len(
                            current_phase_indices
                        ):  # More frames in this phase
                            state["next_action_time"] = now + config.scroll_delay

                        else:  # End of current phase
                            state["current_phase_idx"] += 1
                            next_phase_available = (
                                False  # Check if there's a next non-empty phase
                            )
                            temp_next_phase_idx = state["current_phase_idx"]
                            while temp_next_phase_idx < len(
                                state["all_phases_indices"]
                            ):
                                if state["all_phases_indices"][temp_next_phase_idx]:
                                    next_phase_available = True
                                    state["current_phase_idx"] = temp_next_phase_idx
                                    break
                                temp_next_phase_idx += 1

                            if next_phase_available:  # More phases in this loop
                                state["state"] = "awaiting_phase_delay"
                                state["next_action_time"] = now + config.phase_delay
                                state["current_frame_in_phase_idx"] = (
                                    0  # Reset for next phase
                                )

                            else:  # End of all phases in this loop
                                # Always go to awaiting_end_delay after completing all phases of a loop
                                state["state"] = "awaiting_end_delay"
                                state["next_action_time"] = now + config.end_delay
                                # Loop counter is incremented after this end_delay

                    else:  # Error: frame index out of bounds
                        print(
                            f"Error: Frame index {frame_to_display_idx} OOB for phase {state['current_phase_idx']} line {line_num}. Finished."
                        )
                        if len(config.text) > self.width:
                            self.text(config.text[: self.width], line_num)
                        state["state"] = "finished"
                        state["next_action_time"] = float("inf")
                        active_line_numbers.remove(line_num)

                # State: phase_delay is over
                elif state["state"] == "awaiting_phase_delay":
                    state["state"] = "scrolling"
                    # current_phase_idx points to the next phase, current_frame_in_phase_idx is 0
                    state["next_action_time"] = (
                        now  # Process scrolling action immediately
                    )

                # State: end_delay (after a loop or after final loop) is over
                elif state["state"] == "awaiting_end_delay":
                    state[
                        "current_loop"
                    ] += 1  # Increment loop counter *after* the end_delay

                    # Check if animation should FINISH (loops done or timeout)
                    if (
                        config.loops != 0 and state["current_loop"] >= config.loops
                    ) or (now >= state["end_time"]):
                        # All loops are done. Display final text and finish.
                        if len(config.text) > self.width:  # If it was a scrolling line
                            self.text(config.text[: self.width], line_num)
                        state["state"] = "finished"
                        state["next_action_time"] = float("inf")
                        if line_num in active_line_numbers:
                            active_line_numbers.remove(line_num)

                    else:  # More loops to go: Reset for the new loop and apply start_delay
                        state["state"] = (
                            "awaiting_first_scroll"  # Re-enter start delay state
                        )
                        state["next_action_time"] = (
                            now + config.start_delay
                        )  # Schedule after start_delay

                        # Reset phase and frame for the new loop.
                        # The first frame of the new loop (index 0) will be displayed *before* this start_delay,
                        # and then current_frame_in_phase_idx will be set to 1 for the scrolling part.
                        state["current_phase_idx"] = 0
                        state["current_frame_in_phase_idx"] = (
                            0  # Will be used to display frame 0
                        )

                        # Find first non-empty phase for the new loop
                        temp_initial_phase_idx = 0
                        while (
                            temp_initial_phase_idx < len(state["all_phases_indices"])
                            and not state["all_phases_indices"][temp_initial_phase_idx]
                        ):
                            temp_initial_phase_idx += 1

                        if temp_initial_phase_idx < len(state["all_phases_indices"]):
                            state["current_phase_idx"] = temp_initial_phase_idx
                            # Display the *first frame* of the new loop *before* the start_delay for that loop.
                            first_frame_indices_new_loop = state["all_phases_indices"][
                                state["current_phase_idx"]
                            ]
                            first_frame_text_idx_new_loop = (
                                first_frame_indices_new_loop[0]
                            )
                            first_frame_slice_new_loop = config.text[
                                first_frame_text_idx_new_loop : first_frame_text_idx_new_loop
                                + self.width
                            ]
                            self.text(first_frame_slice_new_loop, line_num)
                            # Now, set current_frame_in_phase_idx to 1 for the scrolling part that happens *after* start_delay
                            state["current_frame_in_phase_idx"] = 1

                        else:  # Error: no non-empty phase for new loop
                            print(
                                f"Error: No non-empty phases for new loop for line {line_num}. Finished."
                            )
                            if len(config.text) > self.width:
                                self.text(config.text[: self.width], line_num)
                            state["state"] = "finished"
                            state["next_action_time"] = float("inf")
                            if line_num in active_line_numbers:
                                active_line_numbers.remove(line_num)

        # Safeguard loop (mostly for static lines or ensuring final state if missed)
        for line_config_final in lines:
            line_num_final = line_config_final.line
            if line_num_final in line_states:
                state = line_states[line_num_final]
                if (
                    state["state"] == "finished"
                    and len(line_config_final.text) > self.width
                ):
                    self.text(line_config_final.text[: self.width], line_num_final)
