# Terms of use - CodeSensai

*Version of 2026-10-11. Non-commercial project; this text does not replace
advice from a lawyer.*

## 1. Purpose

CodeSensai is a development assistant: it reads code, reasons step by step,
proposes and runs code in an isolated environment, with your consent. It is a
**non-commercial project**, provided free of charge, **as is**, with no
guarantee of availability or maintenance.

## 2. What you should know about the answers

- Answers are produced by a **language model**. They can be **wrong,
  incomplete or outdated**, even when they look confident.
- **Review all code before using it** outside CodeSensai, and do not rely on
  the answers for legal, medical, financial or security decisions.

## 3. Running code and actions on your machine

- Before any action that writes or runs something, CodeSensai shows you what
  it will do and **waits for your explicit consent**. No answer means no.
- **You are responsible for what you accept.** Read the code shown before
  saying yes.
- Code runs in a disposable Docker container, without network and without
  access to your files (feature T2); this isolation reduces risks but does
  not remove them. Writing files (`write_file`), however, acts **directly on
  your project**, after your consent and with the diff shown.

## 4. Prohibited uses

You may not use CodeSensai to:
- attack, break into or disrupt a computer system without authorization
  (French Penal Code, art. 323-1 et seq.);
- produce malware or bypass security measures;
- process third parties' personal data without a legal basis;
- infringe other people's intellectual property rights;
- deliberately bypass the guardrails (confirmation, filtering, sandbox).

## 5. Your data

See the [privacy policy](privacy-policy.md). In short: everything stays on
your machine, except what is sent to the model server you configure. **Do not
paste secrets** (API keys, passwords) into the conversation.

## 6. Intellectual property

- The code you write with CodeSensai belongs to you.
- The models used (Qwen3, Qwen3-Coder) and Ollama have their own licences:
  see [licenses.md](licenses.md).
- The licence of CodeSensai's own code has not been chosen yet.

## 7. Liability

The team does its best to make CodeSensai safe, but cannot be held liable for
damage resulting from a wrong answer, from code accepted by the user or from
use contrary to these terms, within the limits set by law.

## 8. Changes

These terms may change with the project. The version in force is this file;
its history is visible in Git.
