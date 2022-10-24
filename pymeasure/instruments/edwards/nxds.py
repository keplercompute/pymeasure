#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2022 PyMeasure Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

from pymeasure.instruments import Instrument
from pymeasure.instruments.validators import strict_discrete_set


class Nxds(Instrument):
    """ Represents the Edwards nXDS (10i) Vacuum Pump
    and provides a low-level interaction with the instrument.
    This could potentially work with Edwards pump that has a RS232 interface.
    This instrument is constructed to only start and stop pump.
    """

    enable = Instrument.setting("!C802 %d",
                                """ Starts/stops pump with default settings.""",
                                validator=strict_discrete_set,
                                values=(0, 1),)

<<<<<<< HEAD
    def __init__(self, resourceName, **kwargs):
        super().__init__(
            resourceName,
=======
    def __init__(self, adapter, **kwargs):
        super().__init__(
            adapter,
>>>>>>> 9f50e169fa62bb4bbfa1ab0256045a314bfb6e59
            "Edwards NXDS Vacuum Pump",
            includeSCPI=False,
            **kwargs
        )
