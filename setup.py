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

# important to collect various modules in the package directory
packages = find_packages(exclude=("tests",))

core_requires = [
    "fastapi==0.77.1",
    "httpx",
    "Jinja2",
    "aiofiles",
    "gunicorn",
    "uvicorn",
    "python-dotenv",
]

# fmt: off
endpoint_requires = [
    "psutil==5.9.3",
    "dbus-python==1.3.2"
]

requires = core_requires + endpoint_requires

extras = {
    "testing": [
        "tox",
        "black",
        "isort",
        "autoflake",
        "mypy",
        "flake8",
        "pytest",
        "pytest-cov",
        "coverage-badge",
        "pytest-mock",
    ],
}

setup(
    name=about["__title__"],
    version=about["__version__"],
    description=about["__description__"],
    author=about["__author__"],
    author_email=about["__author_email__"],
    url=about["__url__"],
    python_requires="~=3.7",
    license=about["__license__"],
    classifiers=[
        "Natural Language :: English",
        "Development Status :: 2 - Pre-Alpha",
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
    install_requires=requires,
    extras_require=extras,
    # entry_points={"console_scripts": ["wlanpi-core=wlanpi_core:__main__"]},
)
