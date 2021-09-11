# WLANPI-CORE TODO

A few of the things that need done (there is __much__ not included in this list):

- [ ] access/error rolling for nginx and gunicorn (prevent SBC disk from filling)
- [ ] embedded database
- [ ] review services
- [ ] review documentation
- [ ] fix lint/mypy errors around style and type annotations
- [ ] github actions
- [ ] packagecloud CI/CD
- [ ] investigate why syslog appears to be going to error.log - do we want this?
- [ ] websockets is not included in uvicorn but uvicorn[standard] which has cruft we don't need. investigate when prototyping websockets. needs addressed in requirements.txt

# IDEAS

- [ ] make backend port configurable? currently using 31415 in nginx configuration file for testing
- [ ] https instead of http? Let's Encrypt?

# DONE

- [X] initial debianization testing
- [X] test unit service 
- [X] handle creation of `apiuser`
- [X] create `/var/log/wlanpi-core` directories
- [X] fix setup.py (bring in static files)