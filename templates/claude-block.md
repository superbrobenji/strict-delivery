## strict-delivery

This repository follows the strict-delivery process. Invoke the `strict-delivery` skill at the start of every session, after a compaction and before every change of any size.

Document locations. These override superpowers' default save paths:

- Specs: `{{specs}}`
- Plans: `{{plans}}`
- Reviews: `{{reviews}}`
- Architecture: `{{architecture}}`
- Project playbooks: `{{playbooks}}`

The base playbook of the strict-delivery plugin is read in place from the plugin; the project playbooks add to it and never replace it.

Precedence, highest first. Where two layers disagree, the higher layer wins:

1. This CLAUDE.md: the managed block and the project text.
2. The strict-delivery skill and its prompt blocks.
3. The project playbook.
4. The base playbook of the strict-delivery plugin.
5. superpowers, unmodified.
