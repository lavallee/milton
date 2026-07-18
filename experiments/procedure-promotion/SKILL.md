# Repeated permission failure recovery

Apply this procedure only when the same operation and input fingerprint has
failed with the same permission or approval error twice and no intervening
state change is known.

Read the structured fields literally and choose exactly one recovery class:

1. If `authorized_equivalent_target` is not null, choose `change_target` and
   name that exact target. This wins even when `policy_change_authorized` is
   also true.
2. Otherwise, if `policy_change_authorized` is true, choose `change_policy`.
3. Otherwise choose `escalate`.

Do not invent an alternate target. A null `authorized_equivalent_target` means
that no target change is authorized for this decision. The boolean
`policy_change_authorized = false` forbids `change_policy`; it does not mean
that the policy should be changed to false.

Equivalent decision table:

| authorized equivalent target | policy change authorized | action |
| --- | --- | --- |
| non-null | either value | `change_target` |
| null | true | `change_policy` |
| null | false | `escalate` |

Never choose `repeat_identical` after the predicate holds. Record the repeated
fingerprint, the specific change or escalation, and the evidence that would
demonstrate success. Task completion alone is not evidence that the permission
failure was resolved by this procedure.
