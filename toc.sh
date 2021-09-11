#!/bin/bash
# thanks Dominik https://ahwhattheheck.wordpress.com/2019/02/08/how-to-create-a-table-of-contents-in-a-github-markdown-formatted-file-with-sed/

grep ^# WORKFLOW.md | sed 'h;s/^#\+\s\+\(.*$\)/(#\L\1)/;s/\s/-/g;
s/\.//g;G;s/\(([^)]\+)\)\n\(\#\+\)\s\+\(.*$\)/\2 [\3]\1/;
s/# /asdyxc /;s/(#/(qweasd/;s/#/  /g;s/asdyxc/*/;s/qweasd/#/;'