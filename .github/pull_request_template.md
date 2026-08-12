## Problem and scope

Describe the user problem and why this change is the smallest safe solution.

## Compatibility

- [ ] Existing class identifiers, Chinese fields, functions, outputs, and workflow links remain compatible, or a migration is documented.

## Security and privacy

- [ ] No new secret, hidden network destination, shell execution, dynamic package installation, or unrelated file access is introduced.
- [ ] Network/data-flow changes are documented and tested.

## Validation

- [ ] `python scripts/validate_repository.py`
- [ ] `python -m pytest -q`
- [ ] README/CHANGELOG/security/privacy documentation updated where needed.
