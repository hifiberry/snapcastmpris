from setuptools import setup, find_packages
import os

# Project description
description = "Snapcast MPRIS bridge"

# Use README.md as long description if available; otherwise, fallback to the description
if os.path.exists("readme.md"):
    with open("readme.md", "r", encoding="utf-8") as fh:
        long_description = fh.read()
else:
    long_description = description

setup(
    name="snapcastmpris",
    version="1.0.0",
    author="HiFiBerry",
    author_email="info@hifiberry.com",
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown" if os.path.exists("readme.md") else "text/plain",
    url="https://github.com/hifiberry/snapcastmpris",
    packages=find_packages(exclude=["build", "dist", "deb", "*.egg-info"]),
    package_dir={"snapcastmpris": "snapcastmpris"},
    py_modules=["snapcastmpris.snapcastmpris"],  # Adjust if snapcastmpris.py contains the main entry point
    entry_points={
        "console_scripts": [
            "snapcastmpris=snapcastmpris.snapcastmpris:main",  # Replace `main` with the entry function
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires=">=3.7",
    install_requires=[
        "pydbus",
        "PyGObject",
    ],
    extras_require={
        "dev": ["pytest", "flake8"],
    },
    include_package_data=True,
    zip_safe=False,
)

