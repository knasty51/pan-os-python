#!/usr/bin/env python

# Copyright (c) 2015, Palo Alto Networks
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# Author: Brian Torres-Gil <btorres-gil@paloaltonetworks.com>

"""User-ID and Dynamic Address Group updates using the User-ID API"""

import logging
import xml.etree.ElementTree as ET
from copy import deepcopy

import pandevice.errors as err
from pandevice import string_or_list
from pandevice import string_or_list_or_none
from pan.xapi import PanXapiError
from pandevice.updater import PanOSVersion


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class UserId(object):
    """User-ID Subsystem of Firewall

    A member of a firewall.Firewall object that has special methods for
    interacting with the User-ID API. This includes login/logout of a user,
    user/group mappings, and dynamic address group tags.

    This class is typically not instantiated by anything but the
    firewall.Firewall class itself. There is an instance of this UserId class
    inside every instantiated firewall.Firewall class.

    Args:
        panfirewall (firewall.Firewall): The firewall this user-id subsystem leverages
        prefix (str): Prefix to use in all IP tag operations for Dynamic Address Groups

    """

    def __init__(self, panfirewall, prefix="", ignore_dup_errors=True):
        # Create a class logger
        self._logger = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.panfirewall = panfirewall
        self.prefix = prefix
        self.ignore_dup_errors = ignore_dup_errors

        # Build the initial uid-message
        self._uidmessage = ET.fromstring("<uid-message>"
                                         "<version>1.0</version>"
                                         "<type>update</type>"
                                         "<payload/>"
                                         "</uid-message>")
        # Batch state
        self._batch = False
        self._batch_uidmessage = deepcopy(self._uidmessage)

    def _create_uidmessage(self):
        if self._batch:
            payload = self._batch_uidmessage.find("payload")
            return self._batch_uidmessage, payload
        else:
            root = deepcopy(self._uidmessage)
            payload = root.find("payload")
            return root, payload

    def batch_start(self):
        """Start creating an API call

        The API call will not be sent to the firewall until batch_end() is
        called. This allows multiple operations to be added to a single API
        call.
        """
        self._batch = True
        self._batch_uidmessage = deepcopy(self._uidmessage)

    def batch_end(self):
        """End a batched API call and send it to the firewall

        This method usually follows a batch_start() and several other
        operations.

        The API call will not be sent to the firewall until batch_end() is
        called. This allows multiple operations to be added to a single API
        call.
        """
        uid_message, payload = self._create_uidmessage()
        self._batch = False
        if len(payload) > 0:
            self.send(uid_message)
        self._batch_uidmessage = deepcopy(self._uidmessage)

    def send(self, uidmessage):
        """Send a uidmessage to the User-ID API of a firewall

        Used for adhoc User-ID API calls that are not supported by other
        methods in this class. This method cannot be batched.

        Args:
            uidmessage (str): The UID Message in XML to send to the firewall

        """
        if self._batch:
            return
        else:
            cmd = ET.tostring(uidmessage)
            try:
                self.panfirewall.xapi.user_id(cmd=cmd, vsys=self.panfirewall.vsys)
            except (err.PanDeviceXapiError, PanXapiError) as e:
                # Check if this is just an error about duplicates or nonexistant tags
                # If so, ignore the error. Most operations don't care about this.
                message = str(e)
                if self.ignore_dup_errors and (message.endswith("already exists, ignore") or message.endswith("does not exist, ignore unreg")):
                    return
                else:
                    raise e

    def login(self, user, ip):
        """Login a single user

        Maps a user to an IP address

        This method can be batched with batch_start() and batch_end().

        Args:
            user (str): a username
            ip (str): an ip address

        """
        root, payload = self._create_uidmessage()
        login = payload.find("login")
        if login is None:
            login = ET.SubElement(payload, "login")
        ET.SubElement(login, "entry", {"name": user, "ip": ip})
        self.send(root)

    def logins(self, users):
        """Login multiple users in the same API call

        This method can be batched with batch_start() and batch_end().

        Args:
            users: a list of sets of user/ip mappings
                   eg. [(user1, 10.0.1.1), (user2, 10.0.1.2)]

        """
        root, payload = self._create_uidmessage()
        login = payload.find("login")
        if login is None:
            login = ET.SubElement(payload, "login")
        for user in users:
            ET.SubElement(login, "entry", {"name": user[0], "ip": user[1]})
        self.send(root)

    def logout(self, user, ip):
        """Logout a single user

        Removes a mapping of a user to an IP address

        This method can be batched with batch_start() and batch_end().

        Args:
            user (str): a username
            ip (str): an ip address

        """
        root, payload = self._create_uidmessage()
        logout = payload.find("logout")
        if logout is None:
            logout = ET.SubElement(payload, "logout")
        ET.SubElement(logout, "entry", {"name": user, "ip": ip})
        self.send(root)

    def logouts(self, users):
        """Logout multiple users in the same API call

        This method can be batched with batch_start() and batch_end().

        Arguments:
            users: a list of sets of user/ip mappings
                   eg. [(user1, 10.0.1.1), (user2, 10.0.1.2)]

        """
        root, payload = self._create_uidmessage()
        logout = payload.find("logout")
        if logout is None:
            logout = ET.SubElement(payload, "logout")
        for user in users:
            ET.SubElement(logout, "entry", {"name": user[0], "ip": user[1]})
        self.send(root)

    def register(self, ip, tags):
        """Register an ip tag for a Dynamic Address Group

        This method can be batched with batch_start() and batch_end().

        Args:
            ip (str): IP address to tag
            tags (str): The tag for the IP address

        """
        root, payload = self._create_uidmessage()
        register = payload.find("register")
        if register is None:
            register = ET.SubElement(payload, "register")
        tagelement = register.find("./entry[@ip='%s']/tag" % ip)
        if tagelement is None:
            entry = ET.SubElement(register, "entry", {"ip": ip})
            tagelement = ET.SubElement(entry, "tag")
        tags = string_or_list(tags)
        tags = list(set(tags))
        tags = [self.prefix+t for t in tags]
        for tag in tags:
            member = ET.SubElement(tagelement, "member")
            member.text = tag
        self.send(root)

    def unregister(self, ip, tags):
        """Unregister an ip tag for a Dynamic Address Group

        This method can be batched with batch_start() and batch_end().

        Args:
            ip (str): IP address with the tag to remove
            tags (str): The tag to remove from the IP address

        """
        root, payload = self._create_uidmessage()
        unregister = payload.find("unregister")
        if unregister is None:
            unregister = ET.SubElement(payload, "unregister")
        tagelement = unregister.find("./entry[@ip='%s']/tag" % ip)
        if tagelement is None:
            entry = ET.SubElement(unregister, "entry", {"ip": ip})
            tagelement = ET.SubElement(entry, "tag")
        tags = string_or_list(tags)
        tags = list(set(tags))
        tags = [self.prefix+t for t in tags]
        for tag in tags:
            member = ET.SubElement(tagelement, "member")
            member.text = tag
        self.send(root)

    def get_registered_ip(self, ip=None, tags=None, prefix=None):
        """Return registered/tagged addresses

        When called without arguments, retrieves all registered addresses

        **Support:** PAN-OS 6.0 and higher

        Args:
            ip (:obj:`list` or :obj:`str`): IP address(es) to get tags for
            tags (:obj:`list` or :obj:`str`): Tag(s) to get
            prefix (str): Override class tag prefix

        Returns:
            dict: ip addresses as keys with tags as values

        """
        if prefix is None:
            prefix = self.prefix
        # Simple check to determine which command to use
        if self.panfirewall and self.panfirewall.version and PanOSVersion('6.1.0') > self.panfirewall.version:
            command = 'show object registered-address'
        else:
            command = 'show object registered-ip'
        # Add arguments to command
        ip = list(set(string_or_list_or_none(ip)))
        tags = list(set(string_or_list_or_none(tags)))
        tags = [prefix+t for t in tags]
        # This should work but doesn't on some PAN-OS versions
        # Commenting it out for now
        #if len(tags) == 1:
        #    command += ' tag "{0}"'.format(tags[0])
        if len(ip) == 1:
            command += ' ip "{0}"'.format(ip[0])
        root = self.panfirewall.op(cmd=command, vsys=self.panfirewall.vsys, cmd_xml=True)
        entries = root.findall("./result/entry")
        addresses = {}
        for entry in entries:
            c_ip = entry.get("ip")
            if ip and c_ip not in ip:
                continue
            members = entry.findall("./tag/member")
            c_tags = []
            for member in members:
                tag = member.text
                if not prefix or tag.startswith(prefix):
                    if not tags or tag in tags:
                        c_tags.append(tag)
            if c_tags:
                addresses[c_ip] = c_tags
        return addresses

    def clear_registered_ip(self, ip=None, tags=None, prefix=None):
        """Unregister registered/tagged addresses

        Removes registered addresses used by dynamic address groups.
        When called without arguments, removes all registered addresses

        **Support:** PAN-OS 6.0 and higher

        Warning:
            This will clear any batch without it being sent, and can't be used as part of a batch.

        Args:
            ip (:obj:`list` or :obj:`str`): IP address(es) to remove tags for
            tags (:obj:`list` or :obj:`str`): Tag(s) to remove
            prefix (str): Override class tag prefix

        """
        addresses = self.get_registered_ip(ip, tags, prefix)
        self.batch_start()
        for ip, tags in addresses.iteritems():
            self.unregister(ip, tags)
        self.batch_end()