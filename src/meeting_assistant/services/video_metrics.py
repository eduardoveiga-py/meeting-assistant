"""Independent measurements of bridge capture and diagnostic preview delivery."""

from collections import deque


class VideoMetrics:
    def __init__(self):
        self.reset()

    def reset(self):
        self.samples = deque()
        self.rendered = 0
        self.last_rendered_sequence = None
        self.bridge_fps = 0.0
        self.preview_fps = 0.0

    def observe(self, now, sequence, rendered=False):
        if self.samples and (sequence < self.samples[-1][1] or now < self.samples[-1][0]):
            self.reset()
        if rendered and sequence != self.last_rendered_sequence:
            self.rendered += 1
            self.last_rendered_sequence = sequence
        self.samples.append((now, sequence, self.rendered))
        while len(self.samples) > 2 and self.samples[1][0] <= now - 2.0:
            self.samples.popleft()
        start, first_sequence, first_rendered = self.samples[0]
        elapsed = now - start
        if elapsed >= 0.5:
            self.bridge_fps = (sequence - first_sequence) / elapsed
            self.preview_fps = (self.rendered - first_rendered) / elapsed
        return round(self.bridge_fps, 1), round(self.preview_fps, 1)
