"""SQLite: solicitações, avisos de privacidade, consentimentos, tokens, auditoria e prévias de lote."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS solicitacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL, cpf TEXT NOT NULL, email TEXT NOT NULL, telefone TEXT NOT NULL,
  justificativa TEXT NOT NULL, ip TEXT, user_agent TEXT,
  status TEXT NOT NULL, uid_sugerido TEXT NOT NULL, uid_final TEXT, organizacao TEXT,
  decidido_por TEXT, motivo TEXT,
  criado_em TEXT NOT NULL, confirmado_em TEXT, decidido_em TEXT,
  link_enviado INTEGER NOT NULL DEFAULT 0,
  origem TEXT NOT NULL DEFAULT 'formulario', convidado_por TEXT
);
CREATE TABLE IF NOT EXISTS avisos (
  versao TEXT PRIMARY KEY, texto TEXT NOT NULL, registrado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consentimentos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  solicitacao_id INTEGER NOT NULL REFERENCES solicitacoes(id),
  versao_aviso TEXT NOT NULL REFERENCES avisos(versao),
  aceito_em TEXT NOT NULL, ip TEXT, user_agent TEXT, email_confirmado_em TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
  hash TEXT PRIMARY KEY, finalidade TEXT NOT NULL, alvo TEXT NOT NULL,
  expira_em TEXT NOT NULL, usado_em TEXT
);
CREATE TABLE IF NOT EXISTS auditoria (
  id INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT NOT NULL, ator TEXT NOT NULL,
  acao TEXT NOT NULL, alvo TEXT, detalhe TEXT
);
CREATE TABLE IF NOT EXISTS email_pendente (
  uid TEXT PRIMARY KEY, email TEXT NOT NULL, pedido_por TEXT NOT NULL, criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lotes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, criado_por TEXT NOT NULL, criado_em TEXT NOT NULL, linhas TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS auditoria_alvo ON auditoria(alvo);
CREATE INDEX IF NOT EXISTS solicitacoes_status ON solicitacoes(status);
CREATE INDEX IF NOT EXISTS solicitacoes_uid_final ON solicitacoes(uid_final);
"""
# colunas novas em bancos criados por versões anteriores (CREATE TABLE IF NOT EXISTS não as adiciona)
_MIGRACOES = {
    "origem": "ALTER TABLE solicitacoes ADD COLUMN origem TEXT NOT NULL DEFAULT 'formulario'",
    "convidado_por": "ALTER TABLE solicitacoes ADD COLUMN convidado_por TEXT",
}

_CAMPOS_BUSCA = ("nome", "cpf", "email", "telefone", "justificativa", "uid_sugerido", "uid_final",
                 "organizacao", "status", "motivo", "decidido_por", "convidado_por")
_ATUALIZAVEIS = {"status", "uid_final", "organizacao", "decidido_por", "motivo", "decidido_em",
                 "link_enviado"}


def _filtro_busca(q: str) -> tuple[str, list]:
    """WHERE (sem a palavra) que acha o trecho q em qualquer campo; termo de CPF/telefone também pelos dígitos."""
    if not q:
        return "1=1", []

    def padrao(termo: str) -> str:
        return "%" + termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    condicoes = [f"{c} LIKE ? ESCAPE '\\'" for c in _CAMPOS_BUSCA]
    params = [padrao(q)] * len(_CAMPOS_BUSCA)
    digitos = re.sub(r"\D", "", q)
    if digitos and re.fullmatch(r"[\d.\-\s()+]+", q):
        condicoes += ["cpf LIKE ? ESCAPE '\\'", "telefone LIKE ? ESCAPE '\\'"]
        params += [padrao(digitos)] * 2
    return "(" + " OR ".join(condicoes) + ")", params


def iso(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        with self._con() as con:
            con.executescript(SCHEMA)
            colunas = {r["name"] for r in con.execute("PRAGMA table_info(solicitacoes)")}
            for coluna, ddl in _MIGRACOES.items():
                if coluna not in colunas:
                    con.execute(ddl)

    @contextmanager
    def _con(self):
        con = sqlite3.connect(self.caminho, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def ok(self) -> bool:
        with self._con() as con:
            con.execute("SELECT 1")
        return True

    # --- solicitações ---
    def criar_solicitacao(self, dados: dict, *, uid_sugerido: str, ip: str, user_agent: str,
                          versao_aviso: str, texto_aviso: str, agora: datetime) -> int:
        t = iso(agora)
        with self._con() as con:
            con.execute("INSERT OR IGNORE INTO avisos (versao, texto, registrado_em) VALUES (?,?,?)",
                        (versao_aviso, texto_aviso, t))
            cur = con.execute(
                "INSERT INTO solicitacoes (nome, cpf, email, telefone, justificativa, ip, user_agent,"
                " status, uid_sugerido, criado_em) VALUES (?,?,?,?,?,?,?,'aguardando_confirmacao',?,?)",
                (dados["nome"], dados["cpf"], dados["email"], dados["telefone"], dados["justificativa"],
                 ip, user_agent, uid_sugerido, t))
            sid = cur.lastrowid
            con.execute("INSERT INTO consentimentos (solicitacao_id, versao_aviso, aceito_em, ip, user_agent)"
                        " VALUES (?,?,?,?,?)", (sid, versao_aviso, t, ip, user_agent))
        return sid

    def criar_convite(self, dados: dict, *, uid: str, organizacao: str, convidado_por: str,
                      agora: datetime) -> int:
        with self._con() as con:
            cur = con.execute(
                "INSERT INTO solicitacoes (nome, cpf, email, telefone, justificativa, status, uid_sugerido,"
                " organizacao, criado_em, origem, convidado_por) VALUES (?,?,?,?,'','convidado',?,?,?,'convite',?)",
                (dados["nome"], dados["cpf"], dados["email"], dados["telefone"], uid, organizacao, iso(agora),
                 convidado_por))
        return cur.lastrowid

    def criar_convite_email(self, email: str, *, organizacao: str, convidado_por: str, agora: datetime) -> int:
        with self._con() as con:
            cur = con.execute(
                "INSERT INTO solicitacoes (nome, cpf, email, telefone, justificativa, status, uid_sugerido,"
                " organizacao, criado_em, origem, convidado_por)"
                " VALUES ('','',?,'','','convidado','',?,?,'convite_email',?)",
                (email, organizacao, iso(agora), convidado_por))
        return cur.lastrowid

    def expirar_convites_do_email(self, email: str, agora: datetime) -> list[int]:
        """Encerra os convites por e-mail ainda não preenchidos deste e-mail e invalida os links."""
        with self._con() as con:
            ids = [r["id"] for r in con.execute(
                "SELECT id FROM solicitacoes WHERE email=? AND status='convidado' AND origem='convite_email'",
                (email,))]
            for sid in ids:
                self._encerrar_convite(con, sid, agora)
        return ids

    def convite_email_aberto(self, email: str) -> int | None:
        with self._con() as con:
            row = con.execute("SELECT id FROM solicitacoes WHERE email=? AND status='convidado' "
                              "AND origem='convite_email' ORDER BY id DESC LIMIT 1", (email,)).fetchone()
        return row["id"] if row else None

    def criar_alteracao(self, dados: dict, *, uid: str, organizacao: str, consentimento: dict,
                        aguardando: bool = False) -> int:
        """Correção de dados de uma conta existente; expira a alteração anterior ainda não decidida da conta.
        aguardando=True: e-mail novo, só vira pendente depois de confirmado."""
        t = iso(consentimento["agora"])
        status = "aguardando_confirmacao" if aguardando else "pendente"
        with self._con() as con:
            con.execute("UPDATE solicitacoes SET status='expirada' WHERE origem='alteracao' AND uid_sugerido=? "
                        "AND status IN ('pendente','aguardando_confirmacao')", (uid,))
            cur = con.execute(
                "INSERT INTO solicitacoes (nome, cpf, email, telefone, justificativa, ip, user_agent, status,"
                " uid_sugerido, organizacao, criado_em, origem) VALUES (?,?,?,?,?,?,?,?,?,?,?,'alteracao')",
                (dados["nome"], dados["cpf"], dados["email"], dados["telefone"], dados["justificativa"],
                 consentimento["ip"], consentimento["user_agent"], status, uid, organizacao, t))
            sid = cur.lastrowid
            self._inserir_consentimento(con, sid, **consentimento)
        return sid

    def alteracao_em_aberto(self, uid: str) -> dict | None:
        """Última correção de dados da conta ainda não decidida: {"id", "status"} ou None."""
        with self._con() as con:
            row = con.execute("SELECT id, status FROM solicitacoes WHERE origem='alteracao' AND uid_sugerido=? "
                              "AND status IN ('aguardando_confirmacao','pendente','aprovando') "
                              "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        return dict(row) if row else None

    def expirar_convites_do_cpf(self, cpf: str, agora: datetime) -> list[int]:
        """Expira os convites ainda não aceitos deste CPF e invalida os links. Retorna os ids."""
        with self._con() as con:
            ids = [r["id"] for r in con.execute("SELECT id FROM solicitacoes WHERE cpf=? AND status='convidado' "
                "AND origem!='convite_email'",
                                                (cpf,))]
            for sid in ids:
                self._encerrar_convite(con, sid, agora)
        return ids

    def convite_aberto_com_uid(self, uid: str, exceto_cpf: str) -> int | None:
        """Convite em aberto de outro CPF que já reserva este uid (o do mesmo CPF será substituído)."""
        with self._con() as con:
            row = con.execute("SELECT id FROM solicitacoes WHERE status='convidado' AND uid_sugerido=? AND cpf!=? "
                              "ORDER BY id LIMIT 1", (uid, exceto_cpf)).fetchone()
        return row["id"] if row else None

    def cancelar_convite(self, sid: int, agora: datetime) -> bool:
        with self._con() as con:
            return self._encerrar_convite(con, sid, agora)

    @staticmethod
    def _encerrar_convite(con, sid: int, agora: datetime) -> bool:
        cur = con.execute("UPDATE solicitacoes SET status='expirada' WHERE id=? AND status='convidado'", (sid,))
        con.execute("UPDATE tokens SET usado_em=? WHERE finalidade='convite' AND alvo=? AND usado_em IS NULL",
                    (iso(agora), f"sol:{sid}"))
        return cur.rowcount == 1

    def aceitar_convite(self, sid: int, dados: dict, *, ip: str, user_agent: str, uid_sugerido: str,
                        status: str, confirmado_em: str | None = None, consentimento: dict | None = None) -> bool:
        """Grava os dados conferidos pela pessoa (e o consentimento, se dado), só se o convite está em aberto."""
        with self._con() as con:
            cur = con.execute(
                "UPDATE solicitacoes SET nome=?, cpf=?, email=?, telefone=?, justificativa=?, ip=?, user_agent=?,"
                " uid_sugerido=?, status=?, confirmado_em=? WHERE id=? AND status='convidado'",
                (dados["nome"], dados["cpf"], dados["email"], dados["telefone"], dados["justificativa"], ip,
                 user_agent, uid_sugerido, status, confirmado_em, sid))
            if cur.rowcount == 1 and consentimento:
                self._inserir_consentimento(con, sid, **consentimento)
        return cur.rowcount == 1

    def devolver_convite(self, sol: dict) -> bool:
        """Desfaz um aceite que aguardava confirmação: volta os dados do convite (`sol`) e o status convidado."""
        with self._con() as con:
            cur = con.execute(
                "UPDATE solicitacoes SET nome=?, cpf=?, email=?, telefone=?, justificativa=?, ip=?, user_agent=?,"
                " uid_sugerido=?, status='convidado', confirmado_em=? WHERE id=? AND status='aguardando_confirmacao'",
                (sol["nome"], sol["cpf"], sol["email"], sol["telefone"], sol["justificativa"], sol["ip"],
                 sol["user_agent"], sol["uid_sugerido"], sol["confirmado_em"], sol["id"]))
            if cur.rowcount == 1:  # convite em aberto não tem consentimento: o do aceite desfeito sai junto
                con.execute("DELETE FROM consentimentos WHERE solicitacao_id=?", (sol["id"],))
        return cur.rowcount == 1

    def registrar_consentimento(self, sid: int, **consentimento) -> None:
        with self._con() as con:
            self._inserir_consentimento(con, sid, **consentimento)

    @staticmethod
    def _inserir_consentimento(con, sid: int, *, versao_aviso: str, texto_aviso: str, ip: str, user_agent: str,
                               agora: datetime, email_confirmado: bool) -> None:
        t = iso(agora)
        con.execute("INSERT OR IGNORE INTO avisos (versao, texto, registrado_em) VALUES (?,?,?)",
                    (versao_aviso, texto_aviso, t))
        con.execute("INSERT INTO consentimentos (solicitacao_id, versao_aviso, aceito_em, ip, user_agent,"
                    " email_confirmado_em) VALUES (?,?,?,?,?,?)",
                    (sid, versao_aviso, t, ip, user_agent, t if email_confirmado else None))

    def expirar_anteriores(self, cpf: str, email: str, exceto_sid: int) -> None:
        with self._con() as con:
            con.execute("UPDATE solicitacoes SET status='expirada' WHERE cpf=? AND email=? AND id!=? "
                        "AND origem!='alteracao' AND status IN ('aguardando_confirmacao','pendente')",
                        (cpf, email, exceto_sid))

    def remover_solicitacao(self, sid: int) -> None:
        with self._con() as con:
            con.execute("DELETE FROM tokens WHERE alvo=?", (f"sol:{sid}",))
            con.execute("DELETE FROM consentimentos WHERE solicitacao_id=?", (sid,))
            con.execute("DELETE FROM solicitacoes WHERE id=?", (sid,))

    def obter(self, sid: int) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM solicitacoes WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def buscar(self, q: str, status: str | None, pagina: int, por_pagina: int = 25) -> list[dict]:
        where, params = _filtro_busca(q)
        if status:
            where += " AND status=?"
            params.append(status)
        with self._con() as con:
            rows = con.execute(f"SELECT * FROM solicitacoes WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                               (*params, por_pagina, (pagina - 1) * por_pagina)).fetchall()
        return [dict(r) for r in rows]

    def contar_por_status(self, q: str) -> dict[str, int]:
        where, params = _filtro_busca(q)
        with self._con() as con:
            rows = con.execute(f"SELECT status, COUNT(*) FROM solicitacoes WHERE {where} GROUP BY status",
                               params).fetchall()
        return {r[0]: r[1] for r in rows}

    def solicitacao_aprovada_do_uid(self, uid: str) -> int | None:
        with self._con() as con:
            row = con.execute("SELECT id FROM solicitacoes WHERE uid_final=? AND status='aprovada' "
                              "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        return row["id"] if row else None

    def atualizar(self, sid: int, **campos) -> None:
        desconhecidos = set(campos) - _ATUALIZAVEIS
        if desconhecidos:
            raise ValueError(f"campos não atualizáveis: {sorted(desconhecidos)}")
        sets = ", ".join(f"{c}=?" for c in campos)
        with self._con() as con:
            con.execute(f"UPDATE solicitacoes SET {sets} WHERE id=?", (*campos.values(), sid))

    def reivindicar(self, sid: int) -> bool:
        """Passa a solicitação de pendente para aprovando; só um pedido concorrente vence."""
        with self._con() as con:
            cur = con.execute("UPDATE solicitacoes SET status='aprovando' WHERE id=? AND status='pendente'", (sid,))
        return cur.rowcount == 1

    def destravar(self, sid: int) -> bool:
        with self._con() as con:
            cur = con.execute("UPDATE solicitacoes SET status='pendente' WHERE id=? AND status='aprovando'", (sid,))
        return cur.rowcount == 1

    def rejeitar(self, sid: int, motivo: str, decidido_por: str, decidido_em: str) -> bool:
        with self._con() as con:
            cur = con.execute("UPDATE solicitacoes SET status='rejeitada', motivo=?, decidido_por=?, decidido_em=? "
                              "WHERE id=? AND status='pendente'", (motivo, decidido_por, decidido_em, sid))
        return cur.rowcount == 1

    def confirmar_email(self, sid: int, agora: datetime) -> bool:
        t = iso(agora)
        with self._con() as con:
            cur = con.execute("UPDATE solicitacoes SET status='pendente', confirmado_em=? "
                              "WHERE id=? AND status='aguardando_confirmacao'", (t, sid))
            if cur.rowcount != 1:
                return False
            con.execute("UPDATE consentimentos SET email_confirmado_em=? WHERE solicitacao_id=?", (t, sid))
        return True

    def expirar_aguardando(self, limite: datetime) -> None:
        with self._con() as con:
            # o prazo conta do último consentimento (aceite do convite); sem ele, da criação — exceto convite,
            # cuja criação é anterior ao aceite: sem consentimento gravado ele não expira por aqui
            con.execute("UPDATE solicitacoes SET status='expirada' WHERE status='aguardando_confirmacao' AND "
                        "COALESCE((SELECT MAX(aceito_em) FROM consentimentos WHERE solicitacao_id=solicitacoes.id),"
                        " CASE WHEN origem='convite' THEN NULL ELSE criado_em END) < ?", (iso(limite),))

    def consentimento(self, sid: int) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM consentimentos WHERE solicitacao_id=?", (sid,)).fetchone()
        return dict(row) if row else None

    # --- tokens ---
    def inserir_token(self, hash_: str, finalidade: str, alvo: str, expira_em: str) -> None:
        with self._con() as con:
            con.execute("INSERT INTO tokens (hash, finalidade, alvo, expira_em) VALUES (?,?,?,?)",
                        (hash_, finalidade, alvo, expira_em))

    def obter_token(self, hash_: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM tokens WHERE hash=?", (hash_,)).fetchone()
        return dict(row) if row else None

    def marcar_token_usado(self, hash_: str, agora: datetime) -> bool:
        with self._con() as con:
            cur = con.execute("UPDATE tokens SET usado_em=? WHERE hash=? AND usado_em IS NULL",
                              (iso(agora), hash_))
        return cur.rowcount == 1

    def invalidar_tokens(self, finalidade: str, alvo: str, agora: datetime) -> None:
        with self._con() as con:
            con.execute("UPDATE tokens SET usado_em=? WHERE finalidade=? AND alvo=? AND usado_em IS NULL",
                        (iso(agora), finalidade, alvo))

    # --- prévias de convite em lote ---
    def criar_lote(self, criado_por: str, linhas: list[dict], agora: datetime, *, expira_antes: datetime) -> int:
        """Grava a prévia; antes, apaga as criadas antes de `expira_antes` (expiradas)."""
        with self._con() as con:
            self._limpar_lotes(con, expira_antes)
            cur = con.execute("INSERT INTO lotes (criado_por, criado_em, linhas) VALUES (?,?,?)",
                              (criado_por, iso(agora), json.dumps(linhas, ensure_ascii=False)))
        return cur.lastrowid

    def obter_lote(self, lid: int, criado_por: str, limite: datetime) -> list[dict] | None:
        """Linhas do lote deste admin; antes, apaga as prévias criadas antes de `limite` (expiradas)."""
        with self._con() as con:
            self._limpar_lotes(con, limite)
            row = con.execute("SELECT linhas FROM lotes WHERE id=? AND criado_por=?", (lid, criado_por)).fetchone()
        return json.loads(row["linhas"]) if row else None

    def limpar_lotes(self, limite: datetime) -> None:
        with self._con() as con:
            self._limpar_lotes(con, limite)

    @staticmethod
    def _limpar_lotes(con, limite: datetime) -> None:
        con.execute("DELETE FROM lotes WHERE criado_em < ?", (iso(limite),))

    def remover_lote(self, lid: int) -> bool:
        with self._con() as con:
            return con.execute("DELETE FROM lotes WHERE id=?", (lid,)).rowcount == 1

    # --- e-mail pendente de confirmação (informado pelo admin) ---
    def gravar_email_pendente(self, uid: str, email: str, pedido_por: str, agora: datetime) -> None:
        with self._con() as con:
            con.execute("INSERT OR REPLACE INTO email_pendente (uid, email, pedido_por, criado_em) VALUES (?,?,?,?)",
                        (uid, email, pedido_por, iso(agora)))

    def email_pendente(self, uid: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM email_pendente WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None

    def remover_email_pendente(self, uid: str) -> None:
        with self._con() as con:
            con.execute("DELETE FROM email_pendente WHERE uid=?", (uid,))

    # --- auditoria ---
    def auditar(self, ator: str, acao: str, alvo: str, detalhe: str, agora: datetime) -> None:
        with self._con() as con:
            con.execute("INSERT INTO auditoria (quando, ator, acao, alvo, detalhe) VALUES (?,?,?,?,?)",
                        (iso(agora), ator, acao, alvo, detalhe))

    def esqueci_senha_recente(self, uid: str, desde: datetime) -> bool:
        """Já houve e-mail de "esqueci minha senha" para esta conta desde `desde`? (ignorados não contam)"""
        with self._con() as con:
            return con.execute(
                "SELECT 1 FROM auditoria WHERE acao='reset_senha' AND alvo=? AND quando>=? "
                "AND detalhe IN ('esqueci_senha', 'esqueci_senha · falha_envio') LIMIT 1",
                (uid, iso(desde))).fetchone() is not None

    def solicitacoes_da_conta(self, uid: str) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT * FROM solicitacoes WHERE uid_final=? OR (origem='alteracao' AND uid_sugerido=?) "
                               "ORDER BY id DESC", (uid, uid)).fetchall()
        return [dict(r) for r in rows]

    def historico_da_conta(self, uid: str, sids: list[int], limite: int = 300) -> list[dict]:
        """Auditoria da conta e das solicitações ligadas a ela, mais recente primeiro."""
        alvos = [uid] + [f"sol:{s}" for s in sids]
        marcas = ",".join("?" * len(alvos))
        with self._con() as con:
            rows = con.execute(f"SELECT * FROM auditoria WHERE alvo IN ({marcas}) ORDER BY id DESC LIMIT ?",
                               (*alvos, limite)).fetchall()
        return [dict(r) for r in rows]

    def historico(self, sid: int) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT * FROM auditoria WHERE alvo=? ORDER BY id", (f"sol:{sid}",)).fetchall()
        return [dict(r) for r in rows]
