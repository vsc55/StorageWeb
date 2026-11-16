// @ts-check
"use strict";
/** Acceso a la carpeta local para el motor de sincronización (rutas relativas POSIX). */

const fs = require("fs/promises");
const path = require("path");

class LocalFs {
  /**
   * @param {string} root  carpeta local (la del espacio de trabajo)
   * @param {(rel: string, isDir?: boolean) => boolean} [skip]
   * @param {(abs: string) => Promise<void>} [trash]  borrar a la papelera (VS Code); si no, se borra
   */
  constructor(root, skip, trash) {
    this.root = root;
    this.skip = skip || (() => false);
    this.trash = trash;
  }

  /** @param {string} rel */
  abs(rel) {
    const target = path.resolve(this.root, ...rel.split("/"));
    const base = path.resolve(this.root);
    if (target !== base && !target.startsWith(base + path.sep)) throw new Error(`Path outside the folder: ${rel}`);
    return target;
  }

  /** @returns {Promise<Map<string, {size: number, mtime: number}>>} */
  async scan() {
    const files = new Map();
    const walk = async (/** @type {string} */ dir) => {
      let items;
      try {
        items = await fs.readdir(path.join(this.root, ...dir.split("/").filter(Boolean)), { withFileTypes: true });
      } catch {
        return;
      }
      for (const item of items) {
        const rel = dir ? `${dir}/${item.name}` : item.name;
        if (item.isSymbolicLink()) continue;  // los enlaces no se siguen (podrían salir de la carpeta)
        if (item.isDirectory()) {
          if (!this.skip(rel, true)) await walk(rel);
        } else if (item.isFile() && !this.skip(rel, false)) {
          let st;
          try {
            st = await fs.stat(this.abs(rel));
          } catch (err) {
            // Borrado entre el listado y el stat (temporales, el -shm de una SQLite abierta…): ya no existe
            if (/** @type {NodeJS.ErrnoException} */ (err).code === "ENOENT") continue;
            throw err;
          }
          files.set(rel, { size: st.size, mtime: Math.floor(st.mtimeMs) });
        }
      }
    };
    await walk("");
    return files;
  }

  /** @param {string} rel */
  async stat(rel) {
    try {
      const st = await fs.stat(this.abs(rel));
      return st.isFile() ? { size: st.size, mtime: Math.floor(st.mtimeMs) } : null;
    } catch {
      return null;
    }
  }

  /** @param {string} rel */
  async read(rel) {
    return fs.readFile(this.abs(rel));
  }

  /** @param {string} rel @param {Buffer} data */
  async write(rel, data) {
    const target = this.abs(rel);
    await fs.mkdir(path.dirname(target), { recursive: true });
    const tmp = `${target}.storageweb-${process.pid}.tmp`;
    await fs.writeFile(tmp, data);
    await fs.rename(tmp, target);  // el editor nunca ve el archivo a medias
    return /** @type {{size: number, mtime: number}} */ (await this.stat(rel));
  }

  /** @param {string} rel */
  async remove(rel) {
    const target = this.abs(rel);
    if (this.trash) await this.trash(target);
    else await fs.rm(target, { force: true });
  }

  /** @param {string} rel @param {string} to */
  async rename(rel, to) {
    await fs.mkdir(path.dirname(this.abs(to)), { recursive: true });
    await fs.rename(this.abs(rel), this.abs(to));
  }
}

module.exports = { LocalFs };
