# -*- coding: utf-8 -*-

import os
from codecs import open
from typing import Dict

try:
    from setuptools import find_packages, setup
except:
    raise ImportError("setuptools is required ...")

here = os.path.abspath(os.path.dirname(__file__))

# load the package's __version__.py module as a dictionary
about: Dict[str, str] = {}
with open(os.path.join(here, "wlanpi_core", "__version__.py"), "r", "utf-8") as f:
    exec(f.read(), about)


def parse_requires(_list):
    requires = list()
    trims = ["#", "piwheels.org"]
    for require in _list:
        if any(match in require for match in trims):
            continue
        requires.append(require)
    requires = list(filter(None, requires))  # remove "" from list
    return requires


# important to collect various modules in the package directory
packages = find_packages(exclude=("tests",))

with open("testing.txt") as f:
    testing = f.read().splitlines()

testing = parse_requires(testing)

extras = {"testing": testing}

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

requires = parse_requires(requirements)

setup(
    name=about["__title__"],
    version=about["__version__"],
    description=about["__description__"],
    author=about["__author__"],
    author_email=about["__author_email__"],
    url=about["__url__"],
    python_requires="~=3.9",
    license=about["__license__"],
    classifiers=[
        "Natural Language :: English",
        "Development Status :: 1 - Planning",
        "Programming Language :: Python :: 3.9",
        "Intended Audience :: System Administrators",
        "Topic :: Utilities",
    ],
    packages=packages,
    project_urls={
        "Documentation": "https://docs.wlanpi.com",
        "Source": "https://github.com/wlan-pi/wlanpi-core",
    },
    include_package_data=True,
    install_requires=requires,
    extras_require=extras,
    entry_points={
        'console_scripts': [
            'boot-info=wlanpi_core.cli.partitions.boot_info:main',
            'test-boot-config=wlanpi_core.cli.partitions.test_boot_config:main',
        ],
    },
)
