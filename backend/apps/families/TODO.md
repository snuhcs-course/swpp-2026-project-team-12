# TODO

## Generalized Tree Structure
- Support multiple members with the same role in one family room (for example, two sons). The current `unique_family_slot` constraint on `(room, slot)` rejects the second `son`; update the model and migration when implementing this.
- Represent relationships between members explicitly instead of relying only on fixed slots. Keep the `(room, user)` uniqueness rule so one user has one membership per room.
