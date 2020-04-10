## Installation

ANANSE runs on Linux. On Windows 10 it will run fine using the [Windows Subsystem for Linux](https://docs.microsoft.com/en-us/windows/wsl/install-win10). Mac OSX should work and is included in the build test. However, as I don't use it myself, unexpected issues might pop up. Let me know, so I can try to fix it.

### The easiest way to install

The preferred way to install ANANSE is by using [conda](https://docs.continuum.io/anaconda). Activate the [bioconda](https://bioconda.github.io/) channel if you haven't used bioconda before.
You only have to do this once.
``` bash
$ conda config --add channels defaults
$ conda config --add channels bioconda
$ conda config --add channels conda-forge
```
You can install ANANSE with one command. In the current environment:
``` bash
$ conda install ananse
```
Or create a specific environment:
``` bash
$ conda create -n ananse python=3 ananse

# Activate the environment before you use ANANSE
$ conda activate ananse
```
ANANSE only supports Python 3. Don't forget to activate the environment with `source activate ananse` whenever you want to use ANANSE.

### Alternative installation

You can also instll ANANSE with `pip`.