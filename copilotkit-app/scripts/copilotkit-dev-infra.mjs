#!/usr/bin/env node
// Warns about missing LLM vendor API keys and missing CopilotKit Intelligence
// configuration before `npm run dev`, then lets the dev server start anyway
// (chat/generations and Intelligence features fail until the values are set).
// Written by `copilotkit init`; safe to delete if you manage env validation
// yourself.
import { existsSync, readFileSync } from 'node:fs';

/** Vendor API keys this scaffold needs before chat and generations will work. */
const REQUIRED_ENV_KEYS = ["DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "OPENAI_API_KEY"].map(key => ({ key }));

/**
 * Hosted CopilotKit Intelligence env var NAMES this scaffold was generated with
 * (no values — those live only in .env). Empty for a non-hosted build. A
 * missing/blank value means the generated .env was overwritten.
 */
const REQUIRED_INTELLIGENCE_KEYS = [
  {
    "key": "INTELLIGENCE_API_URL"
  },
  {
    "key": "INTELLIGENCE_GATEWAY_WS_URL"
  },
  {
    "key": "CPK_INTELLIGENCE_API_KEY"
  }
];

const envFileExists = existsSync('.env');
const envFileContent = envFileExists ? readFileSync('.env', 'utf8') : '';

// Shared detection predicate — authored once in vendor-key-predicate.ts and
// spliced here verbatim so the CLI pre-check (ENT-677) and this gate cannot
// drift. Defines readDotenvValue / isPlaceholderValue / resolveVendorKeyValue /
// findUnsatisfiedVendorKeys.

function readDotenvValue(envFileContent, key) {
  // The key is matched as text, never as a pattern (PE-520).
  const literal = key.replace(/[.*+?^$(){}|[\]\\]/g, '\\$&');
  const re = new RegExp('^\\s*(?:export\\s+)?' + literal + '=(.*)$', 'gm');
  let match;
  let last = null;
  while ((match = re.exec(envFileContent)) !== null) {
    last = match;
  }
  if (!last) {
    return '';
  }
  const raw = last[1].trim();
  if (
    raw.length >= 2 &&
    ((raw.startsWith('"') && raw.endsWith('"')) ||
      (raw.startsWith("'") && raw.endsWith("'")))
  ) {
    return raw.slice(1, -1).trim();
  }
  if (raw.startsWith('#')) {
    return '';
  }
  return raw.replace(/\s+#.*$/, '').trim();
}

function isPlaceholderValue(value) {
  return /^<.*>$/.test(value) || /^your[-_]/i.test(value) || /\.\.\.$/.test(value);
}

function resolveVendorKeyValue(processEnv, envFileContent, key) {
  const fromProcess = ((processEnv && processEnv[key]) || '').trim();
  return fromProcess !== '' ? fromProcess : readDotenvValue(envFileContent, key);
}

function findUnsatisfiedVendorKeys(processEnv, envFileContent, requirements) {
  return requirements
    .map((requirement) => ({
      requirement,
      value: resolveVendorKeyValue(processEnv, envFileContent, requirement.key),
    }))
    .filter(({ value }) => value === '' || isPlaceholderValue(value));
}


const failedKeys = findUnsatisfiedVendorKeys(process.env, envFileContent, REQUIRED_ENV_KEYS)
  .map(({ requirement, value }) => ({ entry: requirement, value }));

if (failedKeys.length === REQUIRED_ENV_KEYS.length) {
  console.warn('No AI provider key detected. The app will start; configure a key in Settings > AI settings, then save and test it.');
}

// Hosted Intelligence config check (ENT-949). Reuses the shared predicate above:
// a key is unsatisfied when missing/blank in both process.env and .env — the
// symptom of an overwritten generated .env. Names the missing keys only; the
// values belong solely in .env, so the fix is to restore it or re-run init.
const intelligenceFailures = findUnsatisfiedVendorKeys(
  process.env,
  envFileContent,
  REQUIRED_INTELLIGENCE_KEYS,
).map(({ requirement }) => requirement);

if (intelligenceFailures.length > 0) {
  console.warn(
    '⚠ CopilotKit Intelligence is not configured — your .env may have been overwritten.',
  );
  for (const entry of intelligenceFailures) {
    console.warn(`  Missing:  ${entry.key}`);
  }
  console.warn(
    'Restore the value(s) in .env, or re-run `copilotkit init` to reconfigure.',
  );
  console.warn(
    'Starting the dev server anyway — Intelligence features will not work until these are set.',
  );
}

process.exit(0);
