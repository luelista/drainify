#!/usr/bin/env python2
# encoding: utf-8
from __future__ import print_function

import argparse
import datetime
import os
import time
import shutil
import signal
import subprocess
import sys
import tempfile as tmp
import urllib2

import dbus
import dbus.mainloop.glib
import eyed3
import gobject

import pa

# url prefix for album covers
IMG_PREFIX = "https://d3rt1990lpmkn.cloudfront.net/320/"

rec_dir = os.getcwd()

# running recorders
running_recs = {}


def set_id3_tags(filename, metadata):
    """Setting the ID3 tags for an audio file.

    :filename: location of the audio file
    :metadata: contains information for the audio file from the dbus event

    """
    audiofile = eyed3.load(filename)
    audiofile.initTag()

    audiofile.tag.artist = metadata['xesam:artist'][0]
    audiofile.tag.album = metadata['xesam:album']
    audiofile.tag.title = metadata['xesam:title']
    audiofile.tag.track_num = int(metadata['xesam:trackNumber'])
    audiofile.tag.disc_num = int(metadata['xesam:discNumber'])

    cover_art_url = metadata['mpris:artUrl']
    _, cover_id = cover_art_url.rsplit('/', 1)
    art_url = IMG_PREFIX + cover_id
    image_data = urllib2.urlopen(art_url).read()

    audiofile.tag.images.set(3, image_data, "image/jpeg", u"")

    audiofile.tag.save()


class Recorder(object):
    """Recording the spotify throught pulse audio."""
    def __init__(self, encoder, recorder, metadata, tmp_name):
        """Recording the stream.

        :encoder:  lame encoding subprocess
        :recorder: pulse audio recording subprocess
        :metadata: track information from dbus event
        :tmp_name: temporary file name for the recording

        """
        self.encoder = encoder
        self.recorder = recorder
        self.metadata = metadata
        self.tmp_name = tmp_name

        length = metadata['Metadata']["mpris:length"]
        # avoid recording the beginning of the next track
        milli_secs = length * 1E-3 - 750
        self.finished_ts = time.time() + length / 1E6

        # handler that stops recording of track
        self.timeout_handler = gobject.timeout_add(int(milli_secs),
                                                   self.stop_recording_cb)

    def stop_handler(self):
        """ Killing running recorders immediately """
        print("%d/%d  %s  stop_handler"%(self.recorder.pid,self.encoder.pid,self.metadata['Metadata']['xesam:title']))
        print("should stop at %f, now its %f"%(self.finished_ts, time.time()))

        # remove timeout handler
        gobject.source_remove(self.timeout_handler)

        if time.time() + 5 >= self.finished_ts:
            print("close enough, calling regular stop")
            self.stop_recording_cb()
        else:
            print("seems to be a skip, killing old recording")

            running_recs.pop(self.recorder.pid)
            os.killpg(self.recorder.pid, signal.SIGKILL)

            # remove temporary file
            os.remove(self.tmp_name)

    def debugout(self, s):
        print("%d/%d  %s  %s"%(self.recorder.pid,self.encoder.pid,self.metadata['Metadata']['xesam:title'], s))

    def stop_recording_cb(self):
        """ Callback for stopping the recording.
        Setting ID3 Tags.
        Moves the temp file to the specific directory.
        """
        self.debugout("stop_recording_cb (timeout) ")
        running_recs.pop(self.recorder.pid)
        os.killpg(self.recorder.pid, signal.SIGKILL)

        self.debugout("recorder killed")
        title = self.metadata['Metadata']['xesam:title']
        artist = self.metadata['Metadata']['xesam:artist'][0]

        final_name = rec_dir + '/%s - %s.mp3' % (artist, title)
        self.debugout("final_name = "+final_name)

        # waiting for encoder to encode the end of stream
        self.debugout("waiting for encoder to exit...")
        self.encoder.wait()
        self.debugout("ok")

        set_id3_tags(self.tmp_name, self.metadata['Metadata'])
        self.debugout("id3 ok")

        # moving temp recording to destination then finished
        shutil.move(self.tmp_name, final_name)

        print("finished recording of %s - %s." % (artist, title))


# TODO: skipping tracks dont work
def recording_handler(sender=None, metadata=None, sig=None):
    print("handler",metadata)
    if "PlaybackStatus" in metadata:
        if metadata['PlaybackStatus'] == 'Paused':
            # dont stop befor last song recording ended
            time.sleep(1.5)
            for pid, rec in running_recs.items():
                rec.stop_handler()
            return
        if metadata['PlaybackStatus'] == 'Stopped':
            return

        if metadata['PlaybackStatus'] == 'Playing':
            if 'Metadata' not in metadata:
                return
            else:
                # message contains metadata and PlaybackStatus means track skipping
                for pid, rec in running_recs.items():
                    if rec.metadata['Metadata']['mpris:trackid'] == metadata['Metadata']['mpris:trackid']:
                        return
                    rec.stop_handler()

    title = metadata['Metadata']['xesam:title']
    artist = metadata['Metadata']['xesam:artist'][0]
    tmp_file = tmp.mktemp(suffix='.mp3')
    print("recording: %s - %s" % (artist, title))

    # not record the end of the last song, so sleep
    #time.sleep(1.0)

    parec = subprocess.Popen(['parec',
                              '--format=s16le',
                              '--rate=44100',
                              '--device=SpotifyGrabberSink.monitor',
                              '--record',
                              ],
                              stdout=subprocess.PIPE,
                              preexec_fn=os.setsid,
                              #shell=True
                          )

    lame = subprocess.Popen(['lame',
                             '-r',  # raw input
                             '-v',  # use vbr
                             '--bitwidth', '16',
                             '--signed',
                             '--little-endian',
                             #'-b', '320', # bitrate
                             '-V', '2',  # quality
                             #'--abr', '320',
                             '--quiet',  # silent output
                             '-s', '44.1',
                             '-', tmp_file],
                            stdin=parec.stdout,
                            preexec_fn=os.setsid,
                            )

    running_recs[parec.pid] = Recorder(lame, parec, metadata, tmp_file)


def debug_handler(sender=None, metadata=None, k2=None):
    print(datetime.datetime.now(), "got signal from ", sender)
    print(metadata.keys())
    print(k2)
    print("")


def cleanup():
    """Kill all running recordings."""
    for pid, rec in running_recs.items():
        rec.stop_handler()

    print("Stop recording.")


def main():
    parser = argparse.ArgumentParser("Record you tracks playing with spotify on pulseaudio.")

    parser.add_argument('--dir',
                        '-d',
                        help="Directory for storing files. (Default: current directory)",
                        type=str)

    args = parser.parse_args()
    if args.dir:
        if not os.path.exists(args.dir):
            create_dir = raw_input("Directory doesn't exists. Create? [y/n] ")
            if create_dir == 'y':
                os.mkdir(args.dir)
            else:
                sys.exit()

        global rec_dir
        rec_dir = os.path.abspath(args.dir)


    # create loopback sink if not exists
    subprocess.check_call("pactl list sinks | grep SpotifyGrabberSink || pactl load-module module-null-sink sink_name=SpotifyGrabberSink", shell=True)

    # init combined sink
    sinks = pa.list_sinks()

    sink_choose = None

    #if len(sinks) > 1:
    #    for i, s in enumerate(sinks):
    #        print("%i: %s" % (i, s))
    for i, s in enumerate(sinks):
        if s == "SpotifyGrabberSink": sink_choose = i

     #   sink_choose = raw_input("Choose your audio device (Default [0]): ")

    # default sink
    #if not sink_choose:
    #    sink_choose = 0

    rec_sink = sinks[int(sink_choose)]
    spot_id = pa.find_spotify_input_sink()
    #combined_sink = pa.create_combined_sink(rec_sink)
    pa.move_sink_input(spot_id)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()

    remote_object = bus.get_object("org.mpris.MediaPlayer2.spotify",
                                   "/org/mpris/MediaPlayer2")

    change_manager = dbus.Interface(remote_object,
                                    'org.freedesktop.DBus.Properties')

    change_manager.connect_to_signal("PropertiesChanged",
                                     recording_handler)

    loop = gobject.MainLoop()

    try:
        print("Start recording on next track.")
        loop.run()
    except KeyboardInterrupt:
        print("Received KeyboardInterrupt. Quiting.")
        #pa.unload_combined_sink(combined_sink)
        cleanup()
        sys.exit()

if __name__ == '__main__':
    main()
