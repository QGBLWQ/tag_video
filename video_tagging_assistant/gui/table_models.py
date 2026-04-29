from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt


class CaseTableModel(QAbstractTableModel):
    HEADERS = ["Case", "Stage", "Tag Source", "Message"]

    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        values = [
            row.get("case_id", ""),
            row.get("stage", ""),
            row.get("tag_source", ""),
            row.get("message", ""),
        ]
        return values[index.column()]
