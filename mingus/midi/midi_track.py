# -*- coding: utf-8 -*-

#    mingus - Music theory Python package, midi_track module.
#    Copyright (C) 2008-2009, Bart Spaans
#    Copyright (C) 2011, Carlo Stemberger
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Methods for working with MIDI data as bytes.

The MIDI file format specification I used can be found here:
http://www.sonicspot.com/guide/midifiles.html
"""
from __future__ import absolute_import, division

from binascii import a2b_hex
from math import log
from struct import pack

from six.moves import range

from mingus.core.keys import Key, major_keys, minor_keys
from mingus.midi.midi_events import *


class MidiTrack(object):

    """A class used to generate MIDI events from the objects in
    mingus.containers."""

    track_data = b""
    delta_time = b"\x00"
    delay = 0
    bpm = 120
    change_instrument = False
    instrument = 1

    def __init__(self, start_bpm=120):
        self.track_data = b""
        self.set_tempo(start_bpm)

    def end_of_track(self):
        """Return the bytes for an end of track meta event."""
        return b"\x00\xff\x2f\x00"

    def play_Note(self, note):
        """Convert a Note object to a midi event and adds it to the
        track_data.

        To set the channel on which to play this note, set Note.channel, the
        same goes for Note.velocity.
        """
        channel = note.channel
        velocity = note.velocity
        if self.change_instrument:
            self.set_instrument(channel, self.instrument)
            self.change_instrument = False

        assert 0 <= velocity <= 0x7F

        self.track_data += self.note_on(channel, int(note) + 12, velocity)

    def play_NoteContainer(self, notecontainer):
        """Convert a mingus.containers.NoteContainer to the equivalent MIDI
        events and add it to the track_data.

        Note.channel and Note.velocity can be set as well.
        """
        if len(notecontainer) <= 1:
            [self.play_Note(x) for x in notecontainer]
        else:
            self.play_Note(notecontainer[0])
            self.set_deltatime(0)
            [self.play_Note(x) for x in notecontainer[1:]]

    def play_Bar(self, bar):
        """Convert a Bar object to MIDI events and write them to the
        track_data."""
        self.set_deltatime(self.delay)
        self.delay = 0
        self.set_meter(bar.meter)
        self.set_deltatime(0)
        self.set_key(bar.key)
        for x in bar:
            tick = int(round((1.0 / x[1]) * 288))
            if x[2] is None or len(x[2]) == 0:
                self.delay += tick
            else:
                self.set_deltatime(self.delay)
                self.delay = 0
                if hasattr(x[2], "bpm"):
                    self.set_deltatime(0)
                    self.set_tempo(x[2].bpm)
                self.play_NoteContainer(x[2])
                self.set_deltatime(self.int_to_varbyte(tick))
                self.stop_NoteContainer(x[2])

    def play_Track(self, track):
        """Convert a Track object to MIDI events and write them to the
        track_data."""
        if hasattr(track, "name"):
            self.set_track_name(track.name)
        self.delay = 0
        instr = track.instrument
        if hasattr(instr, "instrument_nr"):
            self.change_instrument = True
            self.instrument = instr.number
        for bar in track:
            self.play_Bar(bar)

    def stop_Note(self, note):
        """Add a note_off event for note to event_track."""
        channel = note.channel
        velocity = note.velocity
        self.track_data += self.note_off(channel, int(note) + 12, velocity)

    def stop_NoteContainer(self, notecontainer):
        """Add note_off events for each note in the NoteContainer to the
        track_data."""
        # if there is more than one note in the container, the deltatime should
        # be set back to zero after the first one has been stopped
        if len(notecontainer) <= 1:
            [self.stop_Note(x) for x in notecontainer]
        else:
            self.stop_Note(notecontainer[0])
            self.set_deltatime(0)
            [self.stop_Note(x) for x in notecontainer[1:]]

    def set_instrument(self, channel, instr, bank=1):
        """Add a program change and bank select event to the track_data."""
        self.track_data += self.select_bank(channel, bank)
        self.track_data += self.program_change_event(channel, instr)

    def header(self):
        """Return the bytes for the header of track.

        The header contains the length of the track_data, so you'll have to
        call this function when you're done adding data (when you're not
        using get_midi_data).
        """
        chunk_size = a2b_hex("%08x" % (len(self.track_data) + len(self.end_of_track())))
        return TRACK_HEADER + chunk_size

    def get_midi_data(self):
        """Return the MIDI data in bytes for this track.

        Include header, track_data and the end of track meta event.
        """
        return self.header() + self.track_data + self.end_of_track()

    def midi_event(self, event_type, channel, param1, param2=None):
        """Convert and return the parameters as a MIDI event in bytes."""
        assert 0 <= event_type < 16
        assert 0 <= channel < 16
        assert 0 <= param1 <= 0x7F
        assert param2 is None or 0 <= param2 <= 0x7F

        status_byte = channel | (event_type << 4)
        params = [param1]
        if param2 is not None:
            params.append(param2)

        return self.delta_time + bytes([status_byte] + params)

    def note_off(self, channel, note, velocity):
        """Return bytes for a 'note off' event."""
        return self.midi_event(NOTE_OFF, channel, note, velocity)

    def note_on(self, channel, note, velocity):
        """Return bytes for a 'note_on' event."""
        return self.midi_event(NOTE_ON, channel, note, velocity)

    def controller_event(self, channel, contr_nr, contr_val):
        """Return the bytes for a MIDI controller event."""
        return self.midi_event(CONTROLLER, channel, contr_nr, contr_val)

    def reset(self):
        """Reset track_data and delta_time."""
        self.track_data = b""
        self.delta_time = b"\x00"

    def set_deltatime(self, delta_time):
        """Set the delta_time.

        Can be an integer or a variable length byte.
        """
        if isinstance(delta_time, int):
            delta_time = self.int_to_varbyte(delta_time)
        self.delta_time = delta_time

    def select_bank(self, channel, bank):
        """Return the MIDI event for a select bank controller event."""
        return self.controller_event(BANK_SELECT, channel, bank)

    def program_change_event(self, channel, instr):
        """Return the bytes for a program change controller event."""
        return self.midi_event(PROGRAM_CHANGE, channel, instr)

    def set_tempo(self, bpm):
        """Convert the bpm to a midi event and write it to the track_data."""
        self.bpm = bpm
        self.track_data += self.set_tempo_event(self.bpm)

    def set_tempo_event(self, bpm):
        """Calculate the microseconds per quarter note."""
        ms_per_min = 60000000
        mpqn = a2b_hex("%06x" % (ms_per_min // bpm))
        return self.delta_time + META_EVENT + SET_TEMPO + b"\x03" + mpqn

    def set_meter(self, meter=(4, 4)):
        """Add a time signature event for meter to track_data."""
        self.track_data += self.time_signature_event(meter)

    def time_signature_event(self, meter=(4, 4)):
        """Return a time signature event for meter."""
        numer = a2b_hex("%02x" % meter[0])
        denom = a2b_hex("%02x" % int(log(meter[1], 2)))
        return self.delta_time + META_EVENT + TIME_SIGNATURE + b"\x04" + numer + denom + b"\x18\x08"

    def set_key(self, key="C"):
        """Add a key signature event to the track_data."""
        if isinstance(key, Key):
            key = key.name[0]
        self.track_data += self.key_signature_event(key)

    def key_signature_event(self, key="C"):
        """Return the bytes for a key signature event."""
        if str(key).islower():
            val = minor_keys.index(key) - 7
            mode = b"\x01"
        else:
            val = major_keys.index(key) - 7
            mode = b"\x00"
        if val < 0:
            val = 256 + val
        key = a2b_hex("%02x" % val)
        return self.delta_time + META_EVENT + KEY_SIGNATURE + b"\x02" + key + mode

    def set_track_name(self, name):
        """Add a meta event for the track."""
        self.track_data += self.track_name_event(name)

    def track_name_event(self, name):
        """Return the bytes for a track name meta event."""
        l = self.int_to_varbyte(len(name))
        return b"\x00" + META_EVENT + TRACK_NAME + l + name.encode("ascii")

    def int_to_varbyte(self, value):
        """Convert an integer into a variable length byte.

        How it works: the bytes are stored in big-endian (significant bit
        first), the highest bit of the byte (mask 0x80) is set when there
        are more bytes following. The remaining 7 bits (mask 0x7F) are used
        to store the value.
        """
        # Warning: bit kung-fu ahead. The length of the integer in bytes
        length = int(log(max(value, 1), 0x80)) + 1

        # Remove the highest bit and move the bits to the right if length > 1
        bytes = [value >> i * 7 & 0x7F for i in range(length)]
        bytes.reverse()

        # Set the first bit on every one but the last bit.
        for i in range(len(bytes) - 1):
            bytes[i] = bytes[i] | 0x80
        return pack("%sB" % len(bytes), *bytes)
