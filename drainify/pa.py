#!/usr/bin/env python
# encoding: utf-8
from __future__ import print_function

import re
import subprocess


def create_combined_sink(sink):
    """Create combined sink for the given sink.

    :sink: sink name for the slave of combined sink.
    :returns: ID of created combined sink.

    """
    p = subprocess.Popen(['pactl',
                          'load-module',
                          'module-combine-sink',
                          'sink_name=combined',
                          'slaves=%s' % sink
                         ],
                         stdout=subprocess.PIPE)

    out, err = p.communicate()

    return out


def move_sink_input(sink_input_id):
    """Move spotify sink input to created
    combined sink.

    :sink_input_id: ID of spotify sink input

    """
    subprocess.call(['pactl',
                     'move-sink-input',
                     str(sink_input_id),
                     'SpotifyGrabberSink'
                    ])


def find_spotify_input_sink():
    """Find the sink input id of spotify.

    :returns: input sink id of spotify.
    """
    p = subprocess.Popen(['pactl',
                          'list',
                          'sink-inputs'],
                          stdout=subprocess.PIPE)

    out, err = p.communicate()
    inputs = out.split('\n\n')

    for inp in inputs:
        if "media.name = \"Spotify\"" in inp:
            match = re.search('Sink Input \#(\d+)\n', inp)
            return match.group(1)

    # spotify not found
    raise Exception('Please start spotify.')


def list_sinks():
    """List available sinks.

    :returns: a list of names for available sinks.
    """
    p = subprocess.Popen(['pactl',
                          'list',
                          'sinks',
                          'short'],
                          stdout=subprocess.PIPE)

    out, err = p.communicate()
    sinks = []

    for sink in out.split('\n'):
        if sink:
            _, s, _ = sink.split('\t', 2)
            sinks.append(s)

    return sinks


def unload_combined_sink(combined_sink_id):
    """Unload combined sink module for given ID.

    :combined_sink_id: ID for a loaded combined sink.

    """

    p = subprocess.Popen(['pactl',
                          'unload-module',
                          combined_sink_id],
                          stdout=subprocess.PIPE)

    out, err = p.communicate()


def main():
    sinks = list_sinks()
    for i, s in enumerate(sinks):
        print("%i: %s" % (i, s))

    sink_choose = raw_input("Choose your audio device (Default [0]): ")

    # default sink
    if not sink_choose:
        sink_choose = 0

    rec_sink = sinks[sink_choose]
    spot_id = find_spotify_input_sink()
    print("spotify id", spot_id)
    combined_sink = create_combined_sink(rec_sink)
    print("create combined sink", combined_sink)
    move_sink_input(spot_id)
    raw_input("Press key.")
    unload_combined_sink(combined_sink)
    print("unload combined sink.")

if __name__ == '__main__':
    main()
