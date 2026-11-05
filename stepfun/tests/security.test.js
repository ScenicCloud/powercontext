import assert from "node:assert/strict";
import test from "node:test";
import { requestGuard } from "../server/security.js";

function check(headers) {
  let error;
  requestGuard(3000)({ headers }, {}, (result) => {
    error = result;
  });
  return error;
}

test("request guard accepts loopback app and development origins", () => {
  assert.equal(check({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000", "sec-fetch-site": "same-origin" }), undefined);
  assert.equal(check({ host: "localhost:5173", origin: "http://localhost:5173" }), undefined);
});

test("request guard rejects DNS rebinding and cross-site requests", () => {
  assert.equal(check({ host: "attacker.example" }).status, 403);
  assert.equal(check({ host: "127.0.0.1:3000", origin: "https://attacker.example" }).status, 403);
  assert.equal(check({ host: "127.0.0.1:3000", "sec-fetch-site": "cross-site" }).status, 403);
});
