(function () {
  const decodeBase64url = (value) => {
    const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  };

  const encodeBase64url = (value) => {
    const bytes = new Uint8Array(value);
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  };

  window.passkeys = {
    parseCreationOptions(options) {
      if (PublicKeyCredential.parseCreationOptionsFromJSON) {
        return PublicKeyCredential.parseCreationOptionsFromJSON(options);
      }
      return {
        ...options,
        challenge: decodeBase64url(options.challenge),
        user: {...options.user, id: decodeBase64url(options.user.id)},
        excludeCredentials: (options.excludeCredentials || []).map((item) => ({
          ...item, id: decodeBase64url(item.id),
        })),
      };
    },

    parseRequestOptions(options) {
      if (PublicKeyCredential.parseRequestOptionsFromJSON) {
        return PublicKeyCredential.parseRequestOptionsFromJSON(options);
      }
      return {
        ...options,
        challenge: decodeBase64url(options.challenge),
        allowCredentials: (options.allowCredentials || []).map((item) => ({
          ...item, id: decodeBase64url(item.id),
        })),
      };
    },

    credentialToJSON(credential) {
      if (credential.toJSON) return credential.toJSON();
      const response = credential.response;
      const result = {
        id: credential.id,
        rawId: encodeBase64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
          clientDataJSON: encodeBase64url(response.clientDataJSON),
        },
      };
      if (response.attestationObject) {
        result.response.attestationObject = encodeBase64url(response.attestationObject);
        result.response.transports = response.getTransports ? response.getTransports() : [];
      } else {
        result.response.authenticatorData = encodeBase64url(response.authenticatorData);
        result.response.signature = encodeBase64url(response.signature);
        result.response.userHandle = response.userHandle ? encodeBase64url(response.userHandle) : null;
      }
      return result;
    },

    async jsonResponse(response) {
      let data = {};
      try { data = await response.json(); } catch (_error) { /* no JSON body */ }
      if (!response.ok) throw new Error(data.error || "A biometrikus művelet nem sikerült.");
      return data;
    },
  };
})();
