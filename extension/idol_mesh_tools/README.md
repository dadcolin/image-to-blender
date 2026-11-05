# IDOL Mesh Tools

Independent offline mesh importer and sizing add-on, GPL-3.0-or-later.

Use File > Import > IDOL Derived Mesh, or the IDOL sidebar in the 3D View.
Choose a local `mesh-manifest.json` together with its relative mesh-data/source
files. This format is documented at https://github.com/dadcolin/image-to-blender.
Files are treated as data, never as Python scripts. The add-on does not require
an account, Internet, external packages, model weights or inference services.

Object Mode sizes the entire active mesh. Edit Mode sizes selected vertices of
one mesh, for example a manually selected shade or base. Uniform scaling sets
one dimension while preserving proportions. XYZ fitting scales axes separately.
Units are mm/cm/m in world space; local scaling can stretch adjacent faces.
Use Undo and inspect the result. Save your scene explicitly to a new file.

This is not a CAD or segmentation tool. Meshes can contain reconstruction errors,
fragments and open boundaries. Imported colors represent baked appearance.
Do not use dimensions as evidence that unseen real-world geometry is accurate.

Credits: Speridlabs IDOL (https://github.com/speridlabs/idol-sdk) provides the
separate image reconstruction model; Blender (https://www.blender.org/) provides
the editing API. Neither model code nor example assets are included here.
This project is independent and does not claim upstream endorsement or official
Blender Extensions approval.
