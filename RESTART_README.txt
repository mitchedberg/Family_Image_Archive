RESTART CHECKLIST – Family Image Archive
Updated: 2025-12-25 23:02 PT

1. Face datasets
   • All facial embeddings up to Dad Slides are stored (raw + proxy). Remaining source still pending full rerun: Negatives proxy-only buckets (run `python -m cli.faces --source negatives --force`).
   • Face Queue launch: `cd photo_archive && python -m cli.faces_queue --min-confidence 0.4 --min-similarity 0.45`.

2. People export (iPad demo)
   • Config file: `02_WORKING_BUCKETS/config/demo_people.txt` (8 names). Edit before rerun.
   • Command (read-only DB):
     ```
     cd /Volumes/4TB_Sandisk_SSD/Family_Image_Archive/photo_archive
     python -m cli.export_people \
       --archive-root "/Volumes/4TB_Sandisk_SSD/Family_Image_Archive" \
       --out-root "/Volumes/4TB_Sandisk_SSD/Family_Image_Archive/03_PUBLISHED_TO_PHOTOS/DEMO_PEOPLE" \
       --people-file "/Volumes/4TB_Sandisk_SSD/Family_Image_Archive/02_WORKING_BUCKETS/config/demo_people.txt" \
       --variant-policy ai_only \
       --copy-mode hardlink \
       --db-readonly
     ```
   • Only directories touched: `/03_PUBLISHED_TO_PHOTOS/DEMO_PEOPLE` and its `export_manifest.csv`.

3. Launch review UI
   • `cd photo_archive && python -m cli.review --include-all` to rebuild bucket previews and open toolbar chips.

4. Outstanding issues
   • Negatives proxy-only face scan pending.
   • One corrupt PRO_4K PNG and FastFoto back TIFF still need re-export/rescan.
   • Face Queue enhancements backlog (sidebar sorting, pagination) tracked in templates under `photo_archive/templates/faces_queue/`.

5. Apple Photos phase 3 next steps
   • After confirming labels, run `python -m cli.publish --source <label> --prefer-ai --keywords` to refresh `03_PUBLISHED_TO_PHOTOS/<source>` prior to new Photos library creation.

Safe to reboot after confirming no `cli.faces` / `cli.export_people` processes are running (`ps -ef | grep cli`).
