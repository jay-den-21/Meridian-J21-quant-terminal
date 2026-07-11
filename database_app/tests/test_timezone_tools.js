"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  US_EASTERN_TIME_ZONE,
  convertLocalDateTimeToUnix,
  formatUnixSecondsInZone,
} = require("../src/eodhd_codegen_app/static/timezone.js");

test("converts winter U.S. Eastern time to UTC UNIX seconds", () => {
  const converted = convertLocalDateTimeToUnix("2024-01-02T09:30:00");

  assert.equal(converted.timeZone, US_EASTERN_TIME_ZONE);
  assert.equal(converted.unixSeconds, Date.parse("2024-01-02T14:30:00Z") / 1000);
  assert.equal(converted.utcIso, "2024-01-02T14:30:00Z");
});

test("converts summer U.S. Eastern time with second precision", () => {
  const converted = convertLocalDateTimeToUnix("2024-07-09T09:30:15");

  assert.equal(converted.unixSeconds, Date.parse("2024-07-09T13:30:15Z") / 1000);
  assert.equal(converted.utcIso, "2024-07-09T13:30:15Z");
  assert.equal(converted.localInput, "2024-07-09T09:30:15");
});

test("formats a UNIX timestamp back into the Eastern helper input", () => {
  const unixSeconds = Date.parse("2024-07-09T13:30:15Z") / 1000;
  const converted = formatUnixSecondsInZone(unixSeconds);

  assert.equal(converted.localInput, "2024-07-09T09:30:15");
});

test("rejects nonexistent spring daylight-saving time", () => {
  assert.throws(
    () => convertLocalDateTimeToUnix("2024-03-10T02:30:00"),
    (error) => error.code === "nonexistent"
  );
});

test("rejects ambiguous fall daylight-saving time", () => {
  assert.throws(
    () => convertLocalDateTimeToUnix("2024-11-03T01:30:00"),
    (error) => error.code === "ambiguous"
  );
});

test("rejects invalid calendar input", () => {
  assert.throws(
    () => convertLocalDateTimeToUnix("2024-02-30T09:30:00"),
    (error) => error.code === "invalid_local_time"
  );
});
