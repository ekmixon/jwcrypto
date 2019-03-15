# Copyright (C) 2015 JWCrypto Project Contributors - see LICENSE file

from jwcrypto.common import JWException
from jwcrypto.common import JWSEHeaderParameter, JWSEHeaderRegistry
from jwcrypto.common import base64url_decode, base64url_encode
from jwcrypto.common import json_decode, json_encode
from jwcrypto.jwa import JWA
from jwcrypto.jwk import JWK

JWSHeaderRegistry = {
    'alg': JWSEHeaderParameter('Algorithm', False, True, None),
    'jku': JWSEHeaderParameter('JWK Set URL', False, False, None),
    'jwk': JWSEHeaderParameter('JSON Web Key', False, False, None),
    'kid': JWSEHeaderParameter('Key ID', False, True, None),
    'x5u': JWSEHeaderParameter('X.509 URL', False, False, None),
    'x5c': JWSEHeaderParameter('X.509 Certificate Chain', False, False, None),
    'x5t': JWSEHeaderParameter(
        'X.509 Certificate SHA-1 Thumbprint', False, False, None),
    'x5t#S256': JWSEHeaderParameter(
        'X.509 Certificate SHA-256 Thumbprint', False, False, None),
    'typ': JWSEHeaderParameter('Type', False, True, None),
    'cty': JWSEHeaderParameter('Content Type', False, True, None),
    'crit': JWSEHeaderParameter('Critical', True, True, None),
    'b64': JWSEHeaderParameter('Base64url-Encode Payload', True, True, None)
}
"""Registry of valid header parameters"""

default_allowed_algs = [
    'HS256', 'HS384', 'HS512',
    'RS256', 'RS384', 'RS512',
    'ES256', 'ES384', 'ES512',
    'PS256', 'PS384', 'PS512']
"""Default allowed algorithms"""


class InvalidJWSSignature(JWException):
    """Invalid JWS Signature.

    This exception is raised when a signature cannot be validated.
    """

    def __init__(self, message=None, exception=None):
        msg = None
        if message:
            msg = str(message)
        else:
            msg = 'Unknown Signature Verification Failure'
        if exception:
            msg += ' {%s}' % str(exception)
        super(InvalidJWSSignature, self).__init__(msg)


class InvalidJWSObject(JWException):
    """Invalid JWS Object.

    This exception is raised when the JWS Object is invalid and/or
    improperly formatted.
    """

    def __init__(self, message=None, exception=None):
        msg = 'Invalid JWS Object'
        if message:
            msg += ' [%s]' % message
        if exception:
            msg += ' {%s}' % str(exception)
        super(InvalidJWSObject, self).__init__(msg)


class InvalidJWSOperation(JWException):
    """Invalid JWS Object.

    This exception is raised when a requested operation cannot
    be execute due to unsatisfied conditions.
    """

    def __init__(self, message=None, exception=None):
        msg = None
        if message:
            msg = message
        else:
            msg = 'Unknown Operation Failure'
        if exception:
            msg += ' {%s}' % str(exception)
        super(InvalidJWSOperation, self).__init__(msg)


class JWSCore(object):
    """The inner JWS Core object.

    This object SHOULD NOT be used directly, the JWS object should be
    used instead as JWS perform necessary checks on the validity of
    the object and requested operations.

    """

    def __init__(self, alg, key, header, payload, algs=None):
        """Core JWS token handling.

        :param alg: The algorithm used to produce the signature.
            See RFC 7518
        :param key: A (:class:`jwcrypto.jwk.JWK`) key of appropriate
            type for the "alg" provided in the 'protected' json string.
        :param header: A JSON string representing the protected header.
        :param payload(bytes): An arbitrary value
        :param algs: An optional list of allowed algorithms

        :raises ValueError: if the key is not a :class:`JWK` object
        :raises InvalidJWAAlgorithm: if the algorithm is not valid, is
            unknown or otherwise not yet implemented.
        """
        self.alg = alg
        self.engine = self._jwa(alg, algs)
        if not isinstance(key, JWK):
            raise ValueError('key is not a JWK object')
        self.key = key

        if header is not None:
            if isinstance(header, dict):
                self.header = header
                header = json_encode(header)
            else:
                self.header = json_decode(header)

            self.protected = base64url_encode(header.encode('utf-8'))
        else:
            self.header = dict()
            self.protected = ''
        self.payload = payload

    def _jwa(self, name, allowed):
        if allowed is None:
            allowed = default_allowed_algs
        if name not in allowed:
            raise InvalidJWSOperation('Algorithm not allowed')
        return JWA.signing_alg(name)

    def _payload(self):
        if self.header.get('b64', True):
            return base64url_encode(self.payload).encode('utf-8')
        else:
            if isinstance(self.payload, bytes):
                return self.payload
            else:
                return self.payload.encode('utf-8')

    def sign(self):
        """Generates a signature"""
        payload = self._payload()
        sigin = b'.'.join([self.protected.encode('utf-8'), payload])
        signature = self.engine.sign(self.key, sigin)
        return {'protected': self.protected,
                'payload': payload,
                'signature': base64url_encode(signature)}

    def verify(self, signature):
        """Verifies a signature

        :raises InvalidJWSSignature: if the verification fails.
        """
        try:
            payload = self._payload()
            sigin = b'.'.join([self.protected.encode('utf-8'), payload])
            self.engine.verify(self.key, sigin, signature)
        except Exception as e:  # pylint: disable=broad-except
            raise InvalidJWSSignature('Verification failed', repr(e))
        return True


class JWS(object):
    """JSON Web Signature object

    This object represent a JWS token.
    """

    def __init__(self, payload=None, header_registry=None):
        """Creates a JWS object.

        :param payload(bytes): An arbitrary value (optional).
        :param header_registry: Optional additions to the header registry
        """
        self.objects = dict()
        if payload:
            self.objects['payload'] = payload
        self.verifylog = None
        self._allowed_algs = None
        self.header_registry = JWSEHeaderRegistry(JWSHeaderRegistry)
        if header_registry:
            self.header_registry.update(header_registry)

    @property
    def allowed_algs(self):
        """Allowed algorithms.

        The list of allowed algorithms.
        Can be changed by setting a list of algorithm names.
        """

        if self._allowed_algs:
            return self._allowed_algs
        else:
            return default_allowed_algs

    @allowed_algs.setter
    def allowed_algs(self, algs):
        if not isinstance(algs, list):
            raise TypeError('Allowed Algs must be a list')
        self._allowed_algs = algs

    @property
    def is_valid(self):
        return self.objects.get('valid', False)

    # TODO: allow caller to specify list of headers it understands
    # FIXME: Merge and check to be changed to two separate functions
    def _merge_check_headers(self, protected, *headers):
        header = None
        crit = []
        if protected is not None:
            if 'crit' in protected:
                crit = protected['crit']
                # Check immediately if we support these critical headers
                for k in crit:
                    if k not in self.header_registry:
                        raise InvalidJWSObject(
                            'Unknown critical header: "%s"' % k)
                    else:
                        if not self.header_registry[k].supported:
                            raise InvalidJWSObject(
                                'Unsupported critical header: "%s"' % k)
            header = protected
            if 'b64' in header:
                if not isinstance(header['b64'], bool):
                    raise InvalidJWSObject('b64 header must be a boolean')

        for hn in headers:
            if hn is None:
                continue
            if header is None:
                header = dict()
            for h in list(hn.keys()):
                if h in self.header_registry:
                    if self.header_registry[h].mustprotect:
                        raise InvalidJWSObject('"%s" must be protected' % h)
                if h in header:
                    raise InvalidJWSObject('Duplicate header: "%s"' % h)
            header.update(hn)

        for k in crit:
            if k not in header:
                raise InvalidJWSObject('Missing critical header "%s"' % k)

        return header

    # TODO: support selecting key with 'kid' and passing in multiple keys
    def _verify(self, alg, key, payload, signature, protected, header=None):
        p = dict()
        # verify it is a valid JSON object and decode
        if protected is not None:
            p = json_decode(protected)
            if not isinstance(p, dict):
                raise InvalidJWSSignature('Invalid Protected header')
        # merge heders, and verify there are no duplicates
        if header:
            if not isinstance(header, dict):
                raise InvalidJWSSignature('Invalid Unprotected header')

        # Merge and check (critical) headers
        chk_hdrs = self._merge_check_headers(p, header)
        for hdr in chk_hdrs:
            if hdr in self.header_registry:
                if not self.header_registry.check_header(hdr, self):
                    raise InvalidJWSSignature('Failed header check')

        # check 'alg' is present
        if alg is None and 'alg' not in p:
            raise InvalidJWSSignature('No "alg" in headers')
        if alg:
            if 'alg' in p and alg != p['alg']:
                raise InvalidJWSSignature('"alg" mismatch, requested '
                                          '"%s", found "%s"' % (alg,
                                                                p['alg']))
            a = alg
        else:
            a = p['alg']

        # the following will verify the "alg" is supported and the signature
        # verifies
        c = JWSCore(a, key, protected, payload, self._allowed_algs)
        c.verify(signature)

    def verify(self, key, alg=None):
        """Verifies a JWS token.

        :param key: The (:class:`jwcrypto.jwk.JWK`) verification key.
        :param alg: The signing algorithm (optional). usually the algorithm
            is known as it is provided with the JOSE Headers of the token.

        :raises InvalidJWSSignature: if the verification fails.
        """

        self.verifylog = list()
        self.objects['valid'] = False
        obj = self.objects
        if 'signature' in obj:
            try:
                self._verify(alg, key,
                             obj['payload'],
                             obj['signature'],
                             obj.get('protected', None),
                             obj.get('header', None))
                obj['valid'] = True
            except Exception as e:  # pylint: disable=broad-except
                self.verifylog.append('Failed: [%s]' % repr(e))

        elif 'signatures' in obj:
            for o in obj['signatures']:
                try:
                    self._verify(alg, key,
                                 obj['payload'],
                                 o['signature'],
                                 o.get('protected', None),
                                 o.get('header', None))
                    # Ok if at least one verifies
                    obj['valid'] = True
                except Exception as e:  # pylint: disable=broad-except
                    self.verifylog.append('Failed: [%s]' % repr(e))
        else:
            raise InvalidJWSSignature('No signatures availble')

        if not self.is_valid:
            raise InvalidJWSSignature('Verification failed for all '
                                      'signatures' + repr(self.verifylog))

    def _deserialize_signature(self, s):
        o = dict()
        o['signature'] = base64url_decode(str(s['signature']))
        if 'protected' in s:
            p = base64url_decode(str(s['protected']))
            o['protected'] = p.decode('utf-8')
        if 'header' in s:
            o['header'] = s['header']
        return o

    def _deserialize_b64(self, o, protected):
        if protected is None:
            b64n = None
        else:
            p = json_decode(protected)
            b64n = p.get('b64')
            if b64n is not None:
                if not isinstance(b64n, bool):
                    raise InvalidJWSObject('b64 header must be boolean')
        b64 = o.get('b64')
        if b64 == b64n:
            return
        elif b64 is None:
            o['b64'] = b64n
        else:
            raise InvalidJWSObject('conflicting b64 values')

    def deserialize(self, raw_jws, key=None, alg=None):
        """Deserialize a JWS token.

        NOTE: Destroys any current status and tries to import the raw
        JWS provided.

        :param raw_jws: a 'raw' JWS token (JSON Encoded or Compact
         notation) string.
        :param key: A (:class:`jwcrypto.jwk.JWK`) verification key (optional).
         If a key is provided a verification step will be attempted after
         the object is successfully deserialized.
        :param alg: The signing algorithm (optional). usually the algorithm
         is known as it is provided with the JOSE Headers of the token.

        :raises InvalidJWSObject: if the raw object is an invaid JWS token.
        :raises InvalidJWSSignature: if the verification fails.
        """
        self.objects = dict()
        o = dict()
        try:
            try:
                djws = json_decode(raw_jws)
                if 'signatures' in djws:
                    o['signatures'] = list()
                    for s in djws['signatures']:
                        os = self._deserialize_signature(s)
                        o['signatures'].append(os)
                        self._deserialize_b64(o, os.get('protected'))
                else:
                    o = self._deserialize_signature(djws)
                    self._deserialize_b64(o, o.get('protected'))

                if 'payload' in djws:
                    if o.get('b64', True):
                        o['payload'] = base64url_decode(str(djws['payload']))
                    else:
                        o['payload'] = djws['payload']

            except ValueError:
                c = raw_jws.split('.')
                if len(c) != 3:
                    raise InvalidJWSObject('Unrecognized representation')
                p = base64url_decode(str(c[0]))
                if len(p) > 0:
                    o['protected'] = p.decode('utf-8')
                    self._deserialize_b64(o, o['protected'])
                o['payload'] = base64url_decode(str(c[1]))
                o['signature'] = base64url_decode(str(c[2]))

            self.objects = o

        except Exception as e:  # pylint: disable=broad-except
            raise InvalidJWSObject('Invalid format', repr(e))

        if key:
            self.verify(key, alg)

    def add_signature(self, key, alg=None, protected=None, header=None):
        """Adds a new signature to the object.

        :param key: A (:class:`jwcrypto.jwk.JWK`) key of appropriate for
         the "alg" provided.
        :param alg: An optional algorithm name. If already provided as an
         element of the protected or unprotected header it can be safely
         omitted.
        :param potected: The Protected Header (optional)
        :param header: The Unprotected Header (optional)

        :raises InvalidJWSObject: if no payload has been set on the object,
                                  or invalid headers are provided.
        :raises ValueError: if the key is not a :class:`JWK` object.
        :raises ValueError: if the algorithm is missing or is not provided
         by one of the headers.
        :raises InvalidJWAAlgorithm: if the algorithm is not valid, is
         unknown or otherwise not yet implemented.
        """

        if not self.objects.get('payload', None):
            raise InvalidJWSObject('Missing Payload')

        b64 = True

        p = dict()
        if protected:
            if isinstance(protected, dict):
                p = protected
                protected = json_encode(p)
            else:
                p = json_decode(protected)

        # If b64 is present we must enforce criticality
        if 'b64' in list(p.keys()):
            crit = p.get('crit', [])
            if 'b64' not in crit:
                raise InvalidJWSObject('b64 header must always be critical')
            b64 = p['b64']

        if 'b64' in self.objects:
            if b64 != self.objects['b64']:
                raise InvalidJWSObject('Mixed b64 headers on signatures')

        h = None
        if header:
            if isinstance(header, dict):
                h = header
                header = json_encode(header)
            else:
                h = json_decode(header)

        p = self._merge_check_headers(p, h)

        if 'alg' in p:
            if alg is None:
                alg = p['alg']
            elif alg != p['alg']:
                raise ValueError('"alg" value mismatch, specified "alg" '
                                 'does not match JOSE header value')

        if alg is None:
            raise ValueError('"alg" not specified')

        c = JWSCore(alg, key, protected, self.objects['payload'])
        sig = c.sign()

        o = dict()
        o['signature'] = base64url_decode(sig['signature'])
        if protected:
            o['protected'] = protected
        if header:
            o['header'] = h
        o['valid'] = True

        if 'signatures' in self.objects:
            self.objects['signatures'].append(o)
        elif 'signature' in self.objects:
            self.objects['signatures'] = list()
            n = dict()
            n['signature'] = self.objects.pop('signature')
            if 'protected' in self.objects:
                n['protected'] = self.objects.pop('protected')
            if 'header' in self.objects:
                n['header'] = self.objects.pop('header')
            if 'valid' in self.objects:
                n['valid'] = self.objects.pop('valid')
            self.objects['signatures'].append(n)
            self.objects['signatures'].append(o)
        else:
            self.objects.update(o)
            self.objects['b64'] = b64

    def serialize(self, compact=False):
        """Serializes the object into a JWS token.

        :param compact(boolean): if True generates the compact
         representation, otherwise generates a standard JSON format.

        :raises InvalidJWSOperation: if the object cannot serialized
         with the compact representation and `compat` is True.
        :raises InvalidJWSSignature: if no signature has been added
         to the object, or no valid signature can be found.
        """
        if compact:
            if 'signatures' in self.objects:
                raise InvalidJWSOperation("Can't use compact encoding with "
                                          "multiple signatures")
            if 'signature' not in self.objects:
                raise InvalidJWSSignature("No available signature")
            if not self.objects.get('valid', False):
                raise InvalidJWSSignature("No valid signature found")
            if 'protected' in self.objects:
                protected = base64url_encode(self.objects['protected'])
            else:
                protected = ''
            if self.objects.get('payload', False):
                if self.objects.get('b64', True):
                    payload = base64url_encode(self.objects['payload'])
                else:
                    if isinstance(self.objects['payload'], bytes):
                        payload = self.objects['payload'].decode('utf-8')
                    else:
                        payload = self.objects['payload']
                    if '.' in payload:
                        raise InvalidJWSOperation(
                            "Can't use compact encoding with unencoded "
                            "payload that uses the . character")
            else:
                payload = ''
            return '.'.join([protected, payload,
                             base64url_encode(self.objects['signature'])])
        else:
            obj = self.objects
            sig = dict()
            if self.objects.get('payload', False):
                if self.objects.get('b64', True):
                    sig['payload'] = base64url_encode(self.objects['payload'])
                else:
                    sig['payload'] = self.objects['payload']
            if 'signature' in obj:
                if not obj.get('valid', False):
                    raise InvalidJWSSignature("No valid signature found")
                sig['signature'] = base64url_encode(obj['signature'])
                if 'protected' in obj:
                    sig['protected'] = base64url_encode(obj['protected'])
                if 'header' in obj:
                    sig['header'] = obj['header']
            elif 'signatures' in obj:
                sig['signatures'] = list()
                for o in obj['signatures']:
                    if not o.get('valid', False):
                        continue
                    s = {'signature': base64url_encode(o['signature'])}
                    if 'protected' in o:
                        s['protected'] = base64url_encode(o['protected'])
                    if 'header' in o:
                        s['header'] = o['header']
                    sig['signatures'].append(s)
                if len(sig['signatures']) == 0:
                    raise InvalidJWSSignature("No valid signature found")
            else:
                raise InvalidJWSSignature("No available signature")
            return json_encode(sig)

    @property
    def payload(self):
        if 'payload' not in self.objects:
            raise InvalidJWSOperation("Payload not available")
        if not self.is_valid:
            raise InvalidJWSOperation("Payload not verified")
        return self.objects['payload']

    def detach_payload(self):
        self.objects.pop('payload', None)

    @property
    def jose_header(self):
        obj = self.objects
        if 'signature' in obj:
            if 'protected' in obj:
                p = json_decode(obj['protected'])
            else:
                p = None
            return self._merge_check_headers(p, obj.get('header', dict()))
        elif 'signatures' in self.objects:
            jhl = list()
            for o in obj['signatures']:
                jh = dict()
                if 'protected' in o:
                    p = json_decode(o['protected'])
                else:
                    p = None
                jh = self._merge_check_headers(p, o.get('header', dict()))
                jhl.append(jh)
            return jhl
        else:
            raise InvalidJWSOperation("JOSE Header(s) not available")
