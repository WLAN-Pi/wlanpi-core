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
    require_list = list()
    trims = ["#", "piwheels.org"]
    for require in _list:
        if any(match in require for match in trims):
            continue
        require_list.append(require)
    require_list = list(filter(None, require_list))  # remove "" from list
    return require_list


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
)
