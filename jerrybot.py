#! /usr/bin/python

# Copyright 2016 University of Szeged
# Copyright 2016 Akos Kiss
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import ConfigParser # will be configparser once we can move to py3
import os
import random
import StringIO
import subprocess
import sys
import time

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.python import log


default_config = StringIO.StringIO("""
[irc]
server = chat.freenode.net
port = 6667
nick = jerrybot
channel = jerryscript

[jerryscript]
timeout = 5
maxlen = 1024
""")


class JerryBot(irc.IRCClient):

    def __init__(self, config):
        self._config = config
        self.nickname = config.get('irc', 'nick')
        self._channel = config.get('irc', 'channel')
        self._timeout = config.get('jerryscript', 'timeout')
        self._maxlen = config.getint('jerryscript', 'maxlen')

        self._commands = {
            'help': {
                'command': self._command_help,
                'help': 'list available commands'
            },
            'ping': {
                'command': self._command_ping,
                'help': 'a gentle pong to a gentle ping',
            },
            'version': {
                'command': self._command_version,
                'help': 'version of JerryScript',
            },
            'eval': {
                'command': self._command_eval,
                'help': 'eval JavaScript expression (timeout: %s secs, max output length: %s chars)' % (self._timeout, self._maxlen),
            },
            'hi': { 'command': self._command_hi, 'hidden': True },
            'hello': { 'command': self._command_hi, 'hidden': True },
        }

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        log.msg('connected to %s' % (self._config.get('irc', 'server')))

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        log.msg('disconnected from %s: %s' % (self._config.get('irc', 'server'), reason))

    def signedOn(self):
        self.join(self._channel)

    def joined(self, channel):
        log.msg('joined %s' % (channel))

    def privmsg(self, user, channel, msg):
        # no response to private messages
        if channel == self.nickname:
            return

        user = user.split('!', 1)[0]

        # only respond to messages directed at me
        if msg.startswith(self.nickname) and msg.startswith((':', ',', ' '), len(self.nickname)):
            msg = msg[len(self.nickname)+1:].strip()
            log.msg('message from %s: %s' % (user, msg))

            cmd = msg.split(None, 1)[0]
            arg = msg[len(cmd):].strip()
            self._commands.get(cmd, {'command': self._command_unknown})['command'](channel, user, cmd, arg)

    def _command_unknown(self, channel, user, cmd, arg):
        self.msg(channel, '%s: cannot do that (try: %s help)' % (user, self.nickname))

    def _command_help(self, channel, user, cmd, arg):
        help = ''.join(('%s: %s\n' % (name, desc.get('help', '')) for name, desc in sorted(self._commands.items()) if not desc.get('hidden', False)))
        self.msg(channel, '%s: available commands:\n %s' % (user, help))

    def _command_ping(self, channel, user, cmd, arg):
        self.msg(channel, '%s: pong %s' % (user, arg))

    def _command_hi(self, channel, user, cmd, arg):
        greetings = [ 'hi', 'hello', 'hullo', 'nice to meet you', 'how are you?' ]
        self.msg(channel, '%s: %s' % (user, random.choice(greetings)))

    def _command_version(self, channel, user, cmd, arg):
        self.msg(channel, '%s: %s' % (user, self._run_jerry(['--version'])))

    def _command_eval(self, channel, user, cmd, arg):
        self.msg(channel, '%s: %s' % (user, self._run_jerry(['--no-prompt'], inp=arg+'\n')))

    def _run_cmd(self, cmd, inp=None):
        log.msg('executing %s with %s' % (cmd, inp))
        proc = subprocess.Popen(['timeout', self._timeout] + cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out, err = proc.communicate(inp)
        return out, err, proc.returncode

    def _run_jerry(self, args, inp=None):
        repo = self._config.get('jerryscript', 'repo')
        if not repo:
            return 'cannot find jerryscript repository'

        jerry = os.path.join(repo, 'build', 'bin', 'jerry')
        if not os.path.isfile(jerry):
            return 'cannot find jerry interpreter'

        out, err, code = self._run_cmd([jerry] + args, inp=inp)
        if code != 0 or len(err) != 0:
            return 'something went wrong (%s): %s' % (code, err[:self._maxlen])

        return out[:self._maxlen]


class JerryBotFactory(protocol.ClientFactory):

    def __init__(self, config):
        self._config = config

    def buildProtocol(self, addr):
        return JerryBot(self._config)

    def clientConnectionLost(self, connector, reason):
        log.msg('connection lost: %s' % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        log.msg('connection failed: %s' % reason)
        reactor.stop()


def parse_config():
    config = ConfigParser.ConfigParser()
    config.readfp(default_config)

    argparser = argparse.ArgumentParser()
    argparser.add_argument('-s', '--server', metavar='ADDR', help='irc server name (default: %s)' % config.get('irc', 'server'))
    argparser.add_argument('-p', '--port', metavar='PORT', help='irc server port (default: %s)' % config.get('irc', 'port'))
    argparser.add_argument('-n', '--nick', metavar='NAME', help='irc nick (default: %s)' % config.get('irc', 'nick'))
    argparser.add_argument('-c', '--channel', metavar='NAME', help='irc channel (default: %s)' % config.get('irc', 'channel'))
    argparser.add_argument('-r', '--repo', metavar='DIR', help='path to local jerryscript git repository')
    argparser.add_argument('-C', '--config', metavar='FILE', help='config ini file')

    args = argparser.parse_args()
    if args.config:
        config.read(args.config)
    if args.server:
        config.set('irc', 'server', args.server)
    if args.port:
        config.set('irc', 'port', args.port)
    if args.nick:
        config.set('irc', 'nick', args.nick)
    if args.channel:
        config.set('irc', 'channel', args.channel)
    if args.repo:
        config.set('jerryscript', 'repo', args.repo)

    return config


def main():
    # parse input
    config = parse_config()

    # initialize logging
    log.startLogging(sys.stdout)

    # create and connect factory to host and port
    reactor.connectTCP(config.get('irc', 'server'),
                       config.getint('irc', 'port'),
                       JerryBotFactory(config))

    # run bot
    reactor.run()


if __name__ == '__main__':
    main()
