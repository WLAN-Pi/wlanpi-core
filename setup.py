# -*- coding: utf-8 -*-

import os
from codecs import open

from setuptools import find_packages
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))

# load the package's __version__.py module as a dictionary
about = {}
with open(os.path.join(here, "wlanpi_core", "__version__.py"), "r", "utf-8") as f:
    exec(f.read(), about)

packages=find_packages(exclude=('tests',))

with open('./requirements.txt', 'r', encoding='utf-8') as requires:
    requires_list = [line.strip() for line in requires if line and line.strip()]

setup(
    name=about["__title__"],
    version=about["__version__"],
    description=about["__description__"],
    author=about["__author__"],
    author_email=about["__author_email__"],
    url=about["__url__"],
    python_requires="~=3.7,",
    license=about["__license__"],
    classifiers=[
        "Natural Language :: English",
        'Development Status :: 2 - Pre-Alpha',
        "Programming Language :: Python :: 3.7",
        "Intended Audience :: System Administrators",
        "Topic :: Utilities",
    ],
    packages=packages,
    project_urls={
        "Documentation": "https://docs.wlanpi.com",
        "Source": "https://github.com/wlan-pi/wlanpi-core",
    },
    include_package_data=True,
    install_requires=requires_list,
    entry_points={"console_scripts": ["wlanpi-core=wlanpi_core:main"]},
)
