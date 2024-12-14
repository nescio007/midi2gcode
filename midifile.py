#!/usr/bin/env python3

class MidiFile:
    """
    A quick&dirty midi-file parser
    """
    def __init__(self, filename):
        self.tracks = []
        self.format = 0
        self.ntrks = 0
        self.division = 0
        self.ticks_per_second = 0
        with open(filename, 'rb') as f:
            self._parse(f)

    def _read_varlength(self, f):
        n = 0
        while True:
            x = int.from_bytes(f.read(1))
            n <<= 7
            n |= x & 0x7f
            if not x&0x80:
                break
        return n

    def _read_u32(self, f):
        return int.from_bytes(f.read(4), 'big')

    def _read_u16(self, f):
        return int.from_bytes(f.read(2), 'big')

    def _parse_header(self, f):
        hdr = f.read(4)
        assert hdr == b'MThd', f"Expected 'MThd', got {hdr}"
        assert self._read_u32(f) == 6
        self.format = self._read_u16(f)
        self.ntrks = self._read_u16(f)
        self.division = self._read_u16(f)
        if self.division & 0x8000: # parse SMPTE format
            n_frames_per_second = (self.division & 0x7f00) >> 8
            ticks_per_frame = self.division & 0xff
            self.ticks_per_second = n_frame_per_second * ticks_per_frame

    def _msglen(self, statusbyte):
        MSGLEN = {
            0x80: 2, # Note Off
            0x90: 2, # Note On
            0xa0: 2, # Polyphonic Key Pressure
            0xb0: 2, # Control Change
            0xc0: 1, # Program Change
            0xd0: 1, # Channel Pressure
            0xe0: 2, # Pitch Bend
        }
        return MSGLEN[statusbyte & 0xf0]

    def _parse_msg(self, f):
        msg_type = int.from_bytes(f.read(1))
        if msg_type < 0x80: # midi-event, no status
            msg = bytes([msg_type]) + f.read(self._msglen(self._last_msg_type) - 1)
            msg_type = self._last_msg_type
            return msg_type, msg
        elif 0x80 <= msg_type < 0xf0:
            msg = f.read(self._msglen(msg_type))
            self._last_msg_type = msg_type
            return msg_type, msg
        elif msg_type == 0xf0 or msg_type == 0xf7: # midi-event (F0) or sysex-event (F7)
            msg_len = self._read_varlength(f)
            msg = f.read(msg_len)
            return msg_type, msg
        elif msg_type == 0xff: # meta-event
            msg_type = int.from_bytes(f.read(1))
            msg_len = self._read_varlength(f)
            msg = f.read(msg_len)
            if msg_type == 0x51 and not self.ticks_per_second: # parse set-tempo (if not yet set)
                if not self.division&0x8000: # but only for non-SMPTE divisions
                    microseconds_per_quarternote = int.from_bytes(msg, 'big')
                    quarternotes_per_second = 1_000_000/microseconds_per_quarternote
                    self.ticks_per_second = quarternotes_per_second * self.division
            return msg_type, msg
        raise ValueError(f"Unexpected midi-event: {msg_type:02x}")


    def _parse_track(self, f):
        hdr = f.read(4)
        assert hdr == b'MTrk', f"Expected 'MTrk', got {hdr}"
        track_length = self._read_u32(f)
        track = []
        end_pos = f.tell() + track_length
        tick_pos = 0
        while f.tell() < end_pos:
            delta_time = self._read_varlength(f)
            tick_pos += delta_time
            msg_type, msg = self._parse_msg(f)
            track.append((tick_pos, msg_type, msg))
        return track


    def _parse(self, f):
        self._parse_header(f)
        for _ in range(self.ntrks):
            self.tracks.append(self._parse_track(f))

    def note_events(self):
        """
        Return sorted list of note-on and note-off events across all tracks
        """
        events_by_time = {}
        for track in self.tracks:
            for ts, control, msg in track:
                if control&0xe0 == 0x80 : # Note-Off or Note-On
                    channel = control&0x0f
                    key = msg[0]
                    on = control&0xf0 == 0x90 and msg[1] > 0 # only consider this a note-on event if the velocity if greater than 0
                    if ts not in events_by_time:
                        events_by_time[ts] = set()
                    events_by_time[ts].add((on, channel, key))
        min_ts = min(events_by_time.keys(), default=0)
        return sorted((k-min_ts,sorted(v)) for k,v in events_by_time.items())

    def monophone_notes_iter(self):
        """
        Returns sorted list of (duration, {channel -> note})-pairs
        For each channel, only consider the most recently played note
        """
        state = {}
        note_events = self.note_events()
        for (ts, events), (next_ts, _) in zip(note_events, note_events[1:]):
            for on, channel, key in events:
                if not on:
                    if channel in state and state[channel] == key:
                        del state[channel]
                else:
                    state[channel] = key
            duration = next_ts - ts
            yield duration, sorted((k,v) for k,v in state.items())

    def monophone_notes(self):
        return list(self.monophone_notes_iter())


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('midifile')
    args = parser.parse_args()

    mf = MidiFile(args.midifile)
    print(f"Midifile with {len(mf.tracks)} tracks, running at {mf.ticks_per_second} ticks/s")
    for i,track in enumerate(mf.tracks):
        print(f"Track {i}:")
        for t, tp, m in track:
            print(f"\t{t:8d}: {f'{tp:02x}' if tp else '-'} {m.hex(' ')}")
        print("")

    print("Events:")
    for t, events in mf.note_events():
        print(f"\t{t:8}:")
        for on, channel, key in events:
            print(f"\t\tchannel {channel} key {key} {'ON' if on else 'off'}")
    print("")

    print("Notes:")
    for duration, state in mf.monophone_notes():
        print(f"{duration/mf.ticks_per_second:8.3f}s: {', '.join(f'{channel}:{key}' for channel,key in state)}")

if __name__ == '__main__':
    main()
