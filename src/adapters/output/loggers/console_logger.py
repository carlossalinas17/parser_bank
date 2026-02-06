"""
Adaptador de salida: Logger a consola.

Implementación simple de ProcessLogger que imprime eventos a stdout.
Reemplaza todos los print() sueltos del código original con un formato
consistente y un resumen final.

Útil para:
- Desarrollo y debugging.
- Ejecución manual desde terminal.

Para producción/N8N se podría implementar un FileLogger o WebhookLogger
que implemente la misma interfaz sin cambiar el dominio.
"""

from pathlib import Path

from src.domain.ports.process_logger import ProcessLogger


class ConsoleLogger(ProcessLogger):
    """Logger que imprime eventos de procesamiento a consola."""

    def __init__(self) -> None:
        self._archivos_recibidos: int = 0
        self._archivos_procesados: int = 0
        self._archivos_descartados: int = 0
        self._total_movimientos: int = 0
        self._errores: list[dict] = []

    # --- Fase 1: Limpieza ---

    def log_file_received(self, file_path: Path, file_type: str) -> None:
        self._archivos_recibidos += 1
        print(f"  📄 Recibido: {file_path.name} ({file_type})")

    def log_file_skipped(self, file_path: Path, reason: str) -> None:
        self._archivos_descartados += 1
        print(f"  ⏭️  Descartado: {file_path.name} — {reason}")

    # --- Fase 2: Procesamiento ---

    def log_bank_identified(self, file_path: Path, bank_name: str) -> None:
        print(f"  🏦 Banco identificado: {bank_name} — {file_path.name}")

    def log_bank_not_identified(self, file_path: Path) -> None:
        print(f"  ❌ Banco NO identificado: {file_path.name}")

    def log_extraction_start(self, file_path: Path, extractor_name: str) -> None:
        print(f"  🔍 Extrayendo texto ({extractor_name}): {file_path.name}")

    def log_extraction_complete(
        self, file_path: Path, num_pages: int, num_movimientos: int
    ) -> None:
        self._archivos_procesados += 1
        self._total_movimientos += num_movimientos
        print(
            f"  ✅ Completado: {file_path.name} — "
            f"{num_pages} páginas, {num_movimientos} movimientos"
        )

    def log_error(self, file_path: Path, error: Exception) -> None:
        self._errores.append({"archivo": str(file_path.name), "error": str(error)})
        print(f"  ❌ Error: {file_path.name} — {error}")

    # --- Fase 3: Consolidación ---

    def log_consolidation_start(self, num_files: int) -> None:
        print(f"\n📊 Consolidando {num_files} archivos...")

    def log_consolidation_complete(self, output_path: Path) -> None:
        print(f"  ✅ Consolidado generado: {output_path}")

    def log_validation_mismatch(
        self, file_path: Path, field: str, expected: str, actual: str
    ) -> None:
        print(
            f"  ⚠️  Discrepancia en {file_path.name}: "
            f"{field} — esperado: {expected}, calculado: {actual}"
        )

    # --- Resumen ---

    def get_summary(self) -> dict:
        return {
            "archivos_recibidos": self._archivos_recibidos,
            "archivos_procesados": self._archivos_procesados,
            "archivos_descartados": self._archivos_descartados,
            "archivos_con_error": len(self._errores),
            "total_movimientos": self._total_movimientos,
            "errores": self._errores,
        }

    def print_summary(self) -> None:
        """Imprime el resumen final del procesamiento."""
        print("\n" + "=" * 60)
        print("RESUMEN DE PROCESAMIENTO")
        print("=" * 60)
        print(f"  Archivos recibidos:   {self._archivos_recibidos}")
        print(f"  Archivos procesados:  {self._archivos_procesados}")
        print(f"  Archivos descartados: {self._archivos_descartados}")
        print(f"  Archivos con error:   {len(self._errores)}")
        print(f"  Total movimientos:    {self._total_movimientos}")

        if self._errores:
            print("\n  ERRORES:")
            for err in self._errores:
                print(f"    - {err['archivo']}: {err['error']}")

        print("=" * 60)
