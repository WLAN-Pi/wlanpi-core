# Man Page Generation

The package manpage is written in Markdown and we can use pandoc to convert it into the correct format.

## Install Dependencies

arm64 host: 

```
cd ~
wget https://github.com/jgm/pandoc/releases/download/2.12/pandoc-2.12-1-arm64.deb
sudo apt install ~/pandoc-2.12-1-arm64.deb
```

## Generate Man Page

First time:

```
cd {repo}/scripts
chmod +x manpage.sh
```

Run manpage.sh from the scripts dir:

```
./manpage.sh
```

## View Man Page (found in {repo}/debian)

man ./wlanpi-webui.1
