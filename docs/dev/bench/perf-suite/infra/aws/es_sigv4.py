#!/usr/bin/env python3
"""Minimal SigV4-signed request to an OpenSearch Service domain (service 'es').

awscurl pulls in a botocore CRT dependency that isn't available here; this uses
botocore's classic SigV4Auth instead. Creds come from the default chain (ada).

Usage:
  python3 es_sigv4.py <METHOD> <URL> [BODY]
"""
import sys
import urllib.error
import urllib.request

import botocore.session
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = "us-east-1"
SERVICE = "es"


def main():
    method, url = sys.argv[1], sys.argv[2]
    body = sys.argv[3] if len(sys.argv) > 3 else None
    creds = botocore.session.get_session().get_credentials().get_frozen_credentials()
    aws_req = AWSRequest(method=method, url=url,
                         data=(body.encode() if body else None),
                         headers={"Content-Type": "application/json"})
    SigV4Auth(creds, SERVICE, REGION).add_auth(aws_req)
    prepared = aws_req.prepare()
    req = urllib.request.Request(prepared.url, data=prepared.body,
                                 method=method, headers=dict(prepared.headers))
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            print(resp.status)
            print(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code)
        print(e.read().decode())


if __name__ == "__main__":
    main()
