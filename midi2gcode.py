#!/usr/bin/env python3
import math

from midifile import MidiFile

# mm/min/Hz
# e.g., running the X-axis at 1920 mm/min produces a 99 Hz tone
CALIBRATION = {
    'X': 1920/99,
    'Y': 1920/99, 
    'Z':  240/99,
}

# speed ranges that produce audible noise
# also in mm/min
SPEED_RANGES = {
    'X': (1500, 10000),
    'Y': (1500, 10000),
    'Z': (200, 500),
}

# limits of the "build" volume
LIMITS_MM = {
    'X': (10, 210),
    'Y': (10, 210),
    'Z': (10, 210),
}

# map midi-channels to axes
AXIS = {
    0: 'X',
    1: 'Y',
    2: 'Z',
}

def freq_for_note(note):
    """
    map midi-note to frequency
    """
    return 440 * 2**((note-69)/12)

def speed_for_note(axis, note):
    """
    map midi-note to speed for a given axis,
    return 0 if target speed is outside of range
    """
    speed = freq_for_note(note) * CALIBRATION[axis]
    lo, hi = SPEED_RANGES[axis]
    if lo <= speed <= hi:
        return speed
    else:
        return 0


class Midi2Gcode:
    def __init__(self, midifile):
        self.midifile = midifile
        self._last_dir = {
            'X':1,
            'Y':1,
            'Z':1
        }
        self._reset()

    def _reset(self):
        self._pos = {axis: min(limits) for axis, limits in LIMITS_MM.items()}

    def _print_prologue(self):
        print("""
M862.3 P "MK3S" ; printer model check
M862.1 P0.4 ; nozzle diameter check
M115 U3.14.0 ; tell printer latest fw version
M201 X1000 Y1000 Z200 E5000 ; sets maximum accelerations, mm/sec^2
M203 X200 Y200 Z12 E120 ; sets maximum feedrates, mm / sec
M204 S1250 T1250 ; sets acceleration (S) and retract acceleration (R), mm/sec^2
M205 X8.00 Y8.00 Z0.40 E4.50 ; sets the jerk limits, mm/sec
M205 S0 T0 ; sets the minimum extruding and travel feed rate, mm/sec

G21 ; set units to millimeters
G90 ; use absolute coordinates
G28 W ; home without bed leveling
        """)

        print(f"""
G1 X{self._pos['X']:.3f} Y{self._pos['Y']:.3f} Z{self._pos['Z']:.3f} ; move to start position
G4 S1 ; wait a little
        """)


    def _print_epilogue(self):
        print("""
M84 ; disable steppers
        """)

    def move(self, distances):
        """
        Generate positions so that the entire distances are covered
        May split the move into multiple back-and-forth moves to accomodate long distances
        """
        max_distances = {axis: max(abs(self._pos[axis] - l) for l in LIMITS_MM[axis]) for axis in distances.keys()}
        if all(max_distances[axis] >= distance for axis, distance in distances.items()):
            # yep, we can move the entire distance in a single move
            # try to maintain the last direction
            for axis, distance in distances.items():
                lo, hi = LIMITS_MM[axis]
                if lo <= self._pos[axis] + distance*self._last_dir[axis] <= hi:
                    # desired direction fits? all good
                    self._pos[axis] += distance*self._last_dir[axis]
                    continue
                elif lo <= self._pos[axis] -distance*self._last_dir[axis] <= hi:
                    # inverse direction fits? record it
                    self._last_dir[axis] *= -1
                    self._pos[axis] += distance*self._last_dir[axis]
                else:
                    # this case should not happen, as we have checked the distance before!
                    raise ValueError()
                # prefer moving the Z-axis down
                self._last_dir['Z'] = -1
            yield self._pos
        else:
            min_fraction = min(max_distances[axis]/distance for axis, distance in distances.items())
            part1 = {axis: distance*min_fraction for axis, distance in distances.items()}
            yield from self.move(part1)
            part2 = {axis: distance*(1-min_fraction) for axis, distance in distances.items()}
            yield from self.move(part2)



    def generate(self):
        self._reset()
        self._print_prologue()

        for duration, state in self.midifile.monophone_notes():
            duration_seconds = duration/self.midifile.ticks_per_second

            if duration_seconds < 0.01: # skip events shorter than 10ms
                continue
            
            if not state: # no active notes? -> just wait
                print(f"G4 S{duration_seconds:.5}")
                continue
            
            speeds = {AXIS[channel]: speed_for_note(AXIS[channel], key) for channel, key in state}
            speed_combined = math.sqrt(sum(speed*speed for speed in speeds.values())) # combine speed values into global speed

            distances = {axis: duration_seconds * speed/60 for axis, speed in speeds.items()} # speed is in mm/min
            for pos in self.move(distances):
                print(f"G1 X{pos['X']:.3f} Y{pos['Y']:.3f} Z{pos['Z']:.3f} F{speed_combined:.0f}")



        self._print_epilogue()

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('midifile')
    args = parser.parse_args()

    mf = MidiFile(args.midifile)
    m2g = Midi2Gcode(mf)
    m2g.generate()

if __name__ == '__main__':
    main()
