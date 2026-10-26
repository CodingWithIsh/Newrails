# Raw pulls (not committed)

Every network response the project uses is saved here, timestamped, inside a JSON envelope
(source, URL, parameters, pull time). The folder is git-ignored because it is large (~1 GB);
`MANIFEST.csv` (committed) lists each file's size and SHA-256 so a later `make refresh` can be
compared with this one. Re-create it with `make refresh`, `make collect` and `make live`.
