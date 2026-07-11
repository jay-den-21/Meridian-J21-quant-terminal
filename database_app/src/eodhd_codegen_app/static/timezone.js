(function initializeTimeZoneTools(root, factory) {
  const tools = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = tools;
  }
  if (root) {
    root.TimeZoneTools = tools;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function createTimeZoneTools() {
  "use strict";

  const US_EASTERN_TIME_ZONE = "America/New_York";
  const LOCAL_DATE_TIME_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;
  const formatterCache = new Map();

  class TimeZoneConversionError extends Error {
    constructor(code, message) {
      super(message);
      this.name = "TimeZoneConversionError";
      this.code = code;
    }
  }

  function convertLocalDateTimeToUnix(value, timeZone = US_EASTERN_TIME_ZONE) {
    const requested = parseLocalDateTime(value);
    const naiveUtc = Date.UTC(
      requested.year,
      requested.month - 1,
      requested.day,
      requested.hour,
      requested.minute,
      requested.second
    );
    const candidates = [];

    possibleOffsetsForYear(requested.year, timeZone).forEach((offsetMs) => {
      const candidateMs = naiveUtc - offsetMs;
      const actual = partsAt(candidateMs, timeZone);
      if (sameLocalParts(actual, requested) && !candidates.includes(candidateMs)) {
        candidates.push(candidateMs);
      }
    });

    if (candidates.length === 0) {
      throw new TimeZoneConversionError(
        "nonexistent",
        `${value} does not exist in ${timeZone} because of the daylight-saving transition.`
      );
    }
    if (candidates.length > 1) {
      throw new TimeZoneConversionError(
        "ambiguous",
        `${value} occurs twice in ${timeZone} because of the daylight-saving transition. Choose an unambiguous time.`
      );
    }

    return describeEpoch(candidates[0], timeZone);
  }

  function formatUnixSecondsInZone(unixSeconds, timeZone = US_EASTERN_TIME_ZONE) {
    const seconds = Number(unixSeconds);
    if (!Number.isSafeInteger(seconds) || seconds < 0) {
      throw new TimeZoneConversionError("invalid_timestamp", "UNIX timestamp must be a non-negative integer.");
    }
    const epochMs = seconds * 1000;
    if (!Number.isFinite(epochMs) || Number.isNaN(new Date(epochMs).getTime())) {
      throw new TimeZoneConversionError("invalid_timestamp", "UNIX timestamp is outside the supported range.");
    }
    return describeEpoch(epochMs, timeZone);
  }

  function describeEpoch(epochMs, timeZone) {
    const unixSeconds = Math.trunc(epochMs / 1000);
    if (unixSeconds < 0) {
      throw new TimeZoneConversionError("before_epoch", "The selected time is before the UNIX epoch.");
    }
    const parts = partsAt(epochMs, timeZone, true);
    return {
      timeZone,
      unixSeconds,
      utcIso: new Date(epochMs).toISOString().replace(".000Z", "Z"),
      localInput: formatLocalInput(parts),
      localLabel: `${formatLocalLabel(parts)} ${parts.timeZoneName}`,
    };
  }

  function parseLocalDateTime(value) {
    const text = String(value || "").trim();
    const match = LOCAL_DATE_TIME_RE.exec(text);
    if (!match) {
      throw new TimeZoneConversionError(
        "invalid_local_time",
        "Enter date and time through seconds, for example 2024-07-09 09:30:15."
      );
    }
    const parts = {
      year: Number.parseInt(match[1], 10),
      month: Number.parseInt(match[2], 10),
      day: Number.parseInt(match[3], 10),
      hour: Number.parseInt(match[4], 10),
      minute: Number.parseInt(match[5], 10),
      second: Number.parseInt(match[6] || "0", 10),
    };
    const roundTrip = new Date(
      Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
    );
    const isExact =
      roundTrip.getUTCFullYear() === parts.year &&
      roundTrip.getUTCMonth() + 1 === parts.month &&
      roundTrip.getUTCDate() === parts.day &&
      roundTrip.getUTCHours() === parts.hour &&
      roundTrip.getUTCMinutes() === parts.minute &&
      roundTrip.getUTCSeconds() === parts.second;
    if (!isExact) {
      throw new TimeZoneConversionError("invalid_local_time", "The local date/time is invalid.");
    }
    return parts;
  }

  function possibleOffsetsForYear(year, timeZone) {
    const offsets = new Set();
    for (let month = 0; month < 12; month += 1) {
      const sampleMs = Date.UTC(year, month, 15, 12, 0, 0);
      offsets.add(offsetAt(sampleMs, timeZone));
    }
    return offsets;
  }

  function offsetAt(epochMs, timeZone) {
    const wholeSecondMs = Math.trunc(epochMs / 1000) * 1000;
    const parts = partsAt(wholeSecondMs, timeZone);
    const representedAsUtc = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second
    );
    return representedAsUtc - wholeSecondMs;
  }

  function partsAt(epochMs, timeZone, includeName = false) {
    const values = {};
    formatterFor(timeZone, includeName)
      .formatToParts(new Date(epochMs))
      .forEach((part) => {
        if (part.type !== "literal") {
          values[part.type] = part.value;
        }
      });
    return {
      year: Number.parseInt(values.year, 10),
      month: Number.parseInt(values.month, 10),
      day: Number.parseInt(values.day, 10),
      hour: Number.parseInt(values.hour, 10),
      minute: Number.parseInt(values.minute, 10),
      second: Number.parseInt(values.second, 10),
      timeZoneName: values.timeZoneName || timeZone,
    };
  }

  function formatterFor(timeZone, includeName) {
    const key = `${timeZone}:${includeName ? "named" : "plain"}`;
    if (!formatterCache.has(key)) {
      const options = {
        timeZone,
        calendar: "gregory",
        numberingSystem: "latn",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      };
      if (includeName) {
        options.timeZoneName = "short";
      }
      formatterCache.set(key, new Intl.DateTimeFormat("en-US", options));
    }
    return formatterCache.get(key);
  }

  function sameLocalParts(left, right) {
    return (
      left.year === right.year &&
      left.month === right.month &&
      left.day === right.day &&
      left.hour === right.hour &&
      left.minute === right.minute &&
      left.second === right.second
    );
  }

  function formatLocalInput(parts) {
    return `${pad(parts.year, 4)}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(
      parts.minute
    )}:${pad(parts.second)}`;
  }

  function formatLocalLabel(parts) {
    return `${pad(parts.year, 4)}-${pad(parts.month)}-${pad(parts.day)} ${pad(parts.hour)}:${pad(
      parts.minute
    )}:${pad(parts.second)}`;
  }

  function pad(value, length = 2) {
    return String(value).padStart(length, "0");
  }

  return {
    US_EASTERN_TIME_ZONE,
    TimeZoneConversionError,
    convertLocalDateTimeToUnix,
    formatUnixSecondsInZone,
  };
});
