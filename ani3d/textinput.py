"""A small single-line text field: caret, Delete / arrows / Home / End, Ctrl+Backspace (word) and hold-to-repeat.

The window system only reports a key press and a release (GLFW repeats are dropped upstream), so held keys are repeated
here from the frame loop: `update()` fires the held editing key again after a short delay and then at a steady rate."""

REPEATABLE = ("Backspace", "Delete", "ArrowLeft", "ArrowRight")
DELAY, RATE = 0.40, 0.032


class TextInput:
    def __init__(self, text="", limit=120):
        self.text, self.caret, self.limit = text, len(text), limit
        self._held, self._next = None, 0.0

    def set(self, text):
        self.text, self.caret = text, len(text)

    def insert(self, s):
        s = "".join(c for c in s if c.isprintable())
        if s and len(self.text) + len(s) <= self.limit:
            self.text = self.text[:self.caret] + s + self.text[self.caret:]
            self.caret += len(s)

    def key(self, key, mods=()):
        """Apply an editing key. Returns True when the key was an editing key (so the caller shouldn't treat it as a command)."""
        ctrl = "Control" in mods
        t, c = self.text, self.caret
        if key == "Backspace":
            if ctrl:  # delete the word before the caret
                j = c
                while j > 0 and t[j - 1] == " ":
                    j -= 1
                while j > 0 and t[j - 1] != " ":
                    j -= 1
                self.text, self.caret = t[:j] + t[c:], j
            elif c > 0:
                self.text, self.caret = t[:c - 1] + t[c:], c - 1
        elif key == "Delete":
            self.text = t[:c] + t[c + 1:]
        elif key == "ArrowLeft":
            self.caret = max(0, c - 1)
        elif key == "ArrowRight":
            self.caret = min(len(t), c + 1)
        elif key == "Home":
            self.caret = 0
        elif key == "End":
            self.caret = len(t)
        elif key == "u" and ctrl:
            self.text, self.caret = "", 0
        else:
            return False
        return True

    def update(self, now, keys, mods=()):
        """Repeat the editing key that is being held. Returns True when it changed the text."""
        held = next((k for k in REPEATABLE if k in keys), None)
        if held is None:
            self._held = None
            return False
        if held != self._held:
            self._held, self._next = held, now + DELAY  # the first press was already applied by key_down
            return False
        changed = False
        while now >= self._next:
            before = self.text
            self.key(held, mods)
            changed = changed or self.text != before
            self._next += RATE
            if self._next < now - 0.2:
                self._next = now + RATE
        return changed

    def window(self, room):
        """(visible text, caret position in it) for a field that fits `room` characters, keeping the caret in view."""
        room = max(room, 4)
        start = max(0, min(self.caret - room + 1, len(self.text) - room))
        return self.text[start:start + room], self.caret - start
