# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The Windows build (PyInstaller: desktidy.exe + desktidyw.exe, no Python on the PC): the service command, the
--service entry, updates by download, installing into %LOCALAPPDATA%\\Programs\\DeskTidy and removing it again.
Nothing here touches the registry, PATH or the Task Scheduler: those calls are replaced."""

import io
import os
import sys
from contextlib import redirect_stdout
from unittest import mock

from desktidy import cli, explorer, gui, system, updates
from tests.helpers import IsolatedTest


class FrozenTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.extracted = self.folder("Downloads", "DeskTidy")             # where the user extracted the zip
        for name in ("desktidy.exe", "desktidyw.exe"):
            self.write(name, "exe", folder="Downloads\\DeskTidy")
        self.write("base_library.zip", "lib", folder="Downloads\\DeskTidy\\_internal")
        self.home = self.path("LocalAppData", "Programs", "DeskTidy")
        patches = [mock.patch.object(system, "FROZEN", True),
                   mock.patch.object(sys, "executable", os.path.join(self.extracted, "desktidy.exe")),
                   mock.patch.object(system, "program_home", return_value=self.home)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class TestCommands(FrozenTest):
    def test_the_service_runs_in_desktidyw(self):
        self.assertEqual(explorer.service_command(), [os.path.join(self.extracted, "desktidyw.exe"), "--service"])

    def test_desktidyw_service_entry(self):
        with mock.patch.object(sys, "argv", ["desktidyw.exe", "--service", "--once", "--no-ai"]), \
                mock.patch("desktidy.service.main") as service:
            gui.main()
        service.assert_called_once_with(["--once", "--no-ai"])

    def test_updates_are_downloaded(self):
        self.assertEqual(updates.install_kind(), ("the Windows build", []))



class TestHome(IsolatedTest):
    def test_local_app_data(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp}):
            self.assertEqual(system.program_home(), os.path.join(self.tmp, "Programs", "DeskTidy"))


class TestInstall(FrozenTest):
    def test_copies_itself_then_registers_from_there(self):
        with mock.patch.object(cli.more, "running", return_value=False), \
                mock.patch.object(cli.subprocess, "run") as run, redirect_stdout(io.StringIO()):
            run.return_value.returncode = 0
            cli.cmd_install(["--accept"])
        self.assertTrue(os.path.exists(os.path.join(self.home, "desktidy.exe")))
        self.assertTrue(os.path.exists(os.path.join(self.home, "_internal", "base_library.zip")))
        run.assert_called_once_with([os.path.join(self.home, "desktidy.exe"), "install", "--accept"])

    def test_replaces_an_older_version(self):
        self.write("old_only.dll", "old", folder="LocalAppData\\Programs\\DeskTidy\\_internal")
        with mock.patch.object(cli.more, "running", return_value=True), \
                mock.patch.object(cli.more, "stop_service", return_value=True) as stop, redirect_stdout(io.StringIO()):
            exe = cli.install_program()
        stop.assert_called_once()                                          # files of the old version are closed
        self.assertEqual(exe, os.path.join(self.home, "desktidy.exe"))
        self.assertFalse(os.path.exists(os.path.join(self.home, "_internal", "old_only.dll")))
        self.assertFalse(os.path.exists(self.home + ".old") or os.path.exists(self.home + ".new"))

    def test_already_there(self):
        with mock.patch.object(sys, "executable", os.path.join(self.home, "desktidy.exe")):
            self.assertIsNone(cli.install_program())


class TestUninstall(FrozenTest):
    def uninstall(self):
        with mock.patch.object(cli.more, "running", return_value=False), \
                mock.patch.object(system, "autostart_info", return_value={"exists": False}), \
                mock.patch.object(system, "uninstall_command", return_value=False), \
                mock.patch.object(explorer, "uninstall", return_value=False), \
                mock.patch.object(cli.more, "confirm", return_value=True), \
                mock.patch.object(cli.subprocess, "Popen") as popen, redirect_stdout(io.StringIO()):
            cli.cmd_uninstall([])
        return popen

    def test_removes_the_installed_program_only(self):
        os.makedirs(os.path.join(self.home, "_internal"))
        for name in ("desktidy.exe", "desktidyw.exe"):
            open(os.path.join(self.home, name), "w").close()
        with mock.patch.object(sys, "executable", os.path.join(self.home, "desktidy.exe")):
            popen = self.uninstall()
        popen.assert_called_once()
        self.assertIn(f'rmdir /s /q "{self.home}"', popen.call_args[0][0][2])

    def test_never_a_folder_that_is_not_the_installed_program(self):
        self.uninstall().assert_not_called()                               # running from Downloads: left alone
        os.makedirs(self.home)
        with mock.patch.object(sys, "executable", os.path.join(self.home, "desktidy.exe")):
            self.uninstall().assert_not_called()                           # no desktidy.exe, _internal: not ours
