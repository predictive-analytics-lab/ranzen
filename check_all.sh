#!/bin/bash

echo "Begin check..." \
&& black . \
&& python -m pytest -vv tests/ \
&& darglint --docstring-style sphinx -v 2 -z long ranzen \
&& pyright ranzen \
&& pyright tests \
&& echo "Check all complete!"
