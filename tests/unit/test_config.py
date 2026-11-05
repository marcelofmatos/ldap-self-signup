from pathlib import Path

import pytest

from app import config
from app.config import ErroConfig, carregar_config, parse_limite


@pytest.fixture(autouse=True)
def _padrao_ausente(tmp_path, monkeypatch):
    """O caminho padrão do ldap.toml aponta para um arquivo que não existe (testes herméticos)."""
    monkeypatch.setattr(config, "LDAP_CONFIG_PADRAO", tmp_path / "padrao-ausente.toml")


def _env(tmp_path, **extra):
    (tmp_path / "pw").write_text("senha-ldap\n")
    (tmp_path / "sk").write_text("chave\n")
    env = {
        "PUBLIC_URL": "https://cadastro.exemplo/",
        "LDAP_URL": "ldaps://ldap.exemplo:636",
        "LDAP_BIND_DN": "cn=admin,dc=exemplo",
        "LDAP_BIND_PW_FILE": str(tmp_path / "pw"),
        "LDAP_USERS_BASE": "ou=Users,dc=exemplo",
        "LDAP_DEFAULT_GROUP_DN": "cn=Usuario,ou=Groups,dc=exemplo",
        "ADMIN_GROUP_DN": "cn=Cadastro Admins,ou=Groups,dc=exemplo",
        "ADMIN_NOTIFY_EMAIL": "admin@exemplo",
        "SMTP_HOST": "smtp.exemplo",
        "SMTP_FROM": "cadastro@exemplo",
        "SECRET_KEY_FILE": str(tmp_path / "sk"),
    }
    env.update(extra)
    return env


TOML_OK = """
[servidor]
url = "ldaps://ldap.arquivo:636"
bind_dn = "cn=admin,dc=arquivo"
bind_pw_file = "{pw}"

[contas]
base = "ou=Users,dc=arquivo"
grupo_padrao = "cn=Usuario,ou=Groups,dc=arquivo"
gid_padrao = 10500

[admins]
uids = ["beltrano", " Fulano "]
grupo = ""
"""


def _toml(tmp_path, texto=TOML_OK, senha="senha-do-arquivo\n"):
    (tmp_path / "pw-arquivo").write_text(senha)
    caminho = tmp_path / "ldap.toml"
    caminho.write_text(texto.replace("{pw}", str(tmp_path / "pw-arquivo")))
    return caminho


def _env_com_toml(tmp_path, texto=TOML_OK, **kw):
    env = _env(tmp_path, LDAP_CONFIG=str(_toml(tmp_path, texto, **kw)))
    for nome in ("LDAP_URL", "LDAP_BIND_DN", "LDAP_BIND_PW_FILE", "LDAP_USERS_BASE",
                 "LDAP_DEFAULT_GROUP_DN", "ADMIN_GROUP_DN"):
        del env[nome]
    return env


def test_carrega_com_padroes(tmp_path):
    cfg = carregar_config(_env(tmp_path))
    assert cfg.public_url == "https://cadastro.exemplo"
    assert cfg.ldap_bind_pw == "senha-ldap"
    assert cfg.secret_key == "chave"
    assert cfg.smtp_password == ""
    assert cfg.smtp_port == 587 and cfg.smtp_starttls is True
    assert cfg.ldap_default_gid == 10000
    assert cfg.token_ttl_hours == 24 and cfg.convite_ttl_dias == 7
    assert cfg.rate_limit_form == (10, 3600)  # cada solicitação gasta 2 (POST / e POST /confirmar)
    assert cfg.rate_limit_login == (10, 900)
    assert str(cfg.data_dir) == "/data" and str(cfg.template_dir) == "/template"
    assert cfg.cookie_secure is True and cfg.trusted_proxies == 1


def test_falta_obrigatoria(tmp_path):
    env = _env(tmp_path)
    del env["LDAP_URL"]
    with pytest.raises(ErroConfig, match="LDAP_URL"):
        carregar_config(env)


def test_segredo_so_por_arquivo(tmp_path):
    env = _env(tmp_path)
    del env["LDAP_BIND_PW_FILE"]
    env["LDAP_BIND_PW"] = "em-claro"
    with pytest.raises(ErroConfig, match="LDAP_BIND_PW_FILE"):
        carregar_config(env)


@pytest.mark.parametrize("texto,esperado", [
    ("5/hora", (5, 3600)), ("10/15min", (10, 900)), ("3/dia", (3, 86400)), ("2/30s", (2, 30)),
])
def test_parse_limite(texto, esperado):
    assert parse_limite(texto) == esperado


def test_parse_limite_invalido():
    with pytest.raises(ErroConfig):
        parse_limite("cinco")


def test_booleano_estrito(tmp_path):
    with pytest.raises(ErroConfig, match="COOKIE_SECURE"):
        carregar_config(_env(tmp_path, COOKIE_SECURE="yes"))


def test_booleano_false_case_insensitive(tmp_path):
    cfg = carregar_config(_env(tmp_path, SMTP_STARTTLS="False"))
    assert cfg.smtp_starttls is False


def test_smtp_tls_verify_padrao_true(tmp_path):
    assert carregar_config(_env(tmp_path)).smtp_tls_verify is True


def test_smtp_tls_verify_false(tmp_path):
    assert carregar_config(_env(tmp_path, SMTP_TLS_VERIFY="false")).smtp_tls_verify is False


def test_timezone_exibicao(tmp_path):
    assert carregar_config(_env(tmp_path)).timezone_exibicao == "America/Sao_Paulo"
    assert carregar_config(_env(tmp_path, TIMEZONE_EXIBICAO="Europe/Lisbon")).timezone_exibicao == "Europe/Lisbon"
    assert carregar_config(_env(tmp_path, TIMEZONE_EXIBICAO=" ")).timezone_exibicao == "America/Sao_Paulo"


@pytest.mark.parametrize("fuso", ["Marte/Olympus", "../etc/passwd"])
def test_timezone_exibicao_invalido(tmp_path, fuso):
    with pytest.raises(ErroConfig, match="TIMEZONE_EXIBICAO"):
        carregar_config(_env(tmp_path, TIMEZONE_EXIBICAO=fuso))


def test_segredo_vazio(tmp_path):
    env = _env(tmp_path)
    (tmp_path / "sk").write_text("\n")
    with pytest.raises(ErroConfig, match="SECRET_KEY_FILE"):
        carregar_config(env)


def test_segredos_fora_do_repr(tmp_path):
    cfg = carregar_config(_env(tmp_path))
    assert "senha-ldap" not in repr(cfg)
    assert "chave" not in repr(cfg)


# --- v0.3: admins por lista e ldap.toml ---

def test_env_sem_arquivo_continua_funcionando(tmp_path):
    cfg = carregar_config(_env(tmp_path))  # aceite 14
    assert cfg.ldap_url == "ldaps://ldap.exemplo:636"
    assert cfg.admin_group_dn == "cn=Cadastro Admins,ou=Groups,dc=exemplo"
    assert cfg.admin_uids == ()


def test_admin_uids_por_env(tmp_path):
    env = _env(tmp_path, ADMIN_UIDS=" beltrano, Fulano ,")
    del env["ADMIN_GROUP_DN"]
    cfg = carregar_config(env)
    assert cfg.admin_uids == ("beltrano", "fulano")
    assert cfg.admin_group_dn == ""


def test_admin_uids_por_env_invalido(tmp_path):
    with pytest.raises(ErroConfig, match="x!"):
        carregar_config(_env(tmp_path, ADMIN_UIDS="beltrano,x!"))


def test_sem_lista_e_sem_grupo_nao_sobe(tmp_path):
    env = _env(tmp_path)
    del env["ADMIN_GROUP_DN"]
    with pytest.raises(ErroConfig, match="ADMIN_UIDS"):
        carregar_config(env)


def test_le_ldap_toml(tmp_path, caplog):
    caplog.set_level("INFO", logger="ldap-self-signup")
    cfg = carregar_config(_env_com_toml(tmp_path))
    assert cfg.ldap_url == "ldaps://ldap.arquivo:636"
    assert cfg.ldap_bind_dn == "cn=admin,dc=arquivo"
    assert cfg.ldap_bind_pw == "senha-do-arquivo"
    assert cfg.ldap_users_base == "ou=Users,dc=arquivo"
    assert cfg.ldap_default_group_dn == "cn=Usuario,ou=Groups,dc=arquivo"
    assert cfg.ldap_default_gid == 10500
    assert cfg.admin_uids == ("beltrano", "fulano")
    assert cfg.admin_group_dn == ""
    assert f"configuração de LDAP lida de {tmp_path / 'ldap.toml'}" in caplog.text
    assert "senha-do-arquivo" not in caplog.text and "dc=arquivo" not in caplog.text


def test_ldap_toml_de_exemplo_e_valido(tmp_path):
    from pathlib import Path
    exemplo = Path(__file__).parents[2] / "config-exemplo/ldap.toml"
    texto = exemplo.read_text().replace("/run/secrets/ldap_bind_pw", "{pw}")
    cfg = carregar_config(_env_com_toml(tmp_path, texto))
    assert cfg.admin_uids == ("admin",) and cfg.ldap_default_gid == 10000


def test_ldap_toml_vence_env(tmp_path):
    env = _env_com_toml(tmp_path)
    env.update(LDAP_URL="ldaps://ldap.env:636", ADMIN_GROUP_DN="cn=Env,dc=exemplo", ADMIN_UIDS="outro",
               LDAP_DEFAULT_GID="999")
    cfg = carregar_config(env)
    assert cfg.ldap_url == "ldaps://ldap.arquivo:636"
    assert cfg.admin_group_dn == "" and cfg.admin_uids == ("beltrano", "fulano")
    assert cfg.ldap_default_gid == 10500


def test_ldap_toml_grupo_e_gid_padrao(tmp_path):
    texto = TOML_OK.replace("gid_padrao = 10500\n", "").replace('uids = ["beltrano", " Fulano "]\n', "") \
        .replace('grupo = ""', 'grupo = "cn=Admins,dc=arquivo"')
    cfg = carregar_config(_env_com_toml(tmp_path, texto))
    assert cfg.admin_uids == () and cfg.admin_group_dn == "cn=Admins,dc=arquivo"
    assert cfg.ldap_default_gid == 10000


def test_ldap_toml_sem_lista_e_sem_grupo_nao_sobe(tmp_path):
    texto = TOML_OK.replace('uids = ["beltrano", " Fulano "]', "uids = []")
    with pytest.raises(ErroConfig, match="ADMIN_UIDS"):
        carregar_config(_env_com_toml(tmp_path, texto))


@pytest.mark.parametrize("texto", [
    TOML_OK.replace('bind_pw_file = "{pw}"', 'bind_pw_file = "{pw}"\nbind_pw = "em-claro"'),
    TOML_OK.replace("[contas]", 'bind_pw = "em-claro"\n[contas]'),
    'bind_pw = "em-claro"\n' + TOML_OK,
])
def test_ldap_toml_recusa_bind_pw(tmp_path, texto):
    with pytest.raises(ErroConfig, match="senha não pode ficar no ldap.toml; use bind_pw_file"):
        carregar_config(_env_com_toml(tmp_path, texto))


@pytest.mark.parametrize("texto,nome", [
    (TOML_OK.replace("gid_padrao", "gid_padro"), "contas.gid_padro"),
    (TOML_OK.replace("[admins]", "[admin]"), "admin"),
    ("url_extra = 1\n" + TOML_OK, "url_extra"),
])
def test_ldap_toml_chave_desconhecida(tmp_path, texto, nome):
    with pytest.raises(ErroConfig, match=f"desconhecida.*{nome}"):
        carregar_config(_env_com_toml(tmp_path, texto))


@pytest.mark.parametrize("chave", ["url", "bind_dn", "bind_pw_file", "base", "grupo_padrao"])
def test_ldap_toml_obrigatorias(tmp_path, chave):
    linhas = [l for l in TOML_OK.splitlines() if not l.startswith(f"{chave} =")]
    with pytest.raises(ErroConfig, match=chave):
        carregar_config(_env_com_toml(tmp_path, "\n".join(linhas)))


def test_ldap_toml_senha_vazia(tmp_path):
    with pytest.raises(ErroConfig, match="bind_pw_file"):
        carregar_config(_env_com_toml(tmp_path, senha="\n"))


def test_ldap_toml_uid_invalido(tmp_path):
    texto = TOML_OK.replace('" Fulano "', '"x!"')
    with pytest.raises(ErroConfig, match="x!"):
        carregar_config(_env_com_toml(tmp_path, texto))


@pytest.mark.parametrize("de,para", [
    ("gid_padrao = 10500", 'gid_padrao = "10500"'),
    ('uids = ["beltrano", " Fulano "]', 'uids = "beltrano"'),
    ('url = "ldaps://ldap.arquivo:636"', "url = 636"),
])
def test_ldap_toml_tipos(tmp_path, de, para):
    with pytest.raises(ErroConfig):
        carregar_config(_env_com_toml(tmp_path, TOML_OK.replace(de, para)))


def test_ldap_toml_invalido(tmp_path):
    with pytest.raises(ErroConfig, match="ldap.toml"):
        carregar_config(_env_com_toml(tmp_path, "[servidor\nurl ="))


# --- erros claros para ldap.toml ausente/ilegível ---

def test_ldap_config_explicito_inexistente(tmp_path):
    faltando = tmp_path / "faltando.toml"
    with pytest.raises(ErroConfig, match=f"LDAP_CONFIG aponta para arquivo inexistente: {faltando}"):
        carregar_config(_env(tmp_path, LDAP_CONFIG=str(faltando)))


def test_ldap_config_padrao_ausente_usa_env(tmp_path):
    assert carregar_config(_env(tmp_path)).ldap_url == "ldaps://ldap.exemplo:636"


def test_ldap_config_explicito_diretorio(tmp_path):
    pasta = tmp_path / "ldap.toml"
    pasta.mkdir()
    with pytest.raises(ErroConfig, match=f"{pasta} não é um arquivo"):
        carregar_config(_env(tmp_path, LDAP_CONFIG=str(pasta)))


def test_ldap_config_padrao_diretorio(tmp_path, monkeypatch):
    # bind mount de arquivo inexistente: o Docker cria uma pasta no lugar
    pasta = tmp_path / "config-ldap.toml"
    pasta.mkdir()
    monkeypatch.setattr(config, "LDAP_CONFIG_PADRAO", pasta)
    with pytest.raises(ErroConfig, match=f"{pasta} não é um arquivo"):
        carregar_config(_env(tmp_path))


def test_ldap_toml_ilegivel(tmp_path, monkeypatch):
    env = _env_com_toml(tmp_path)
    ler = Path.read_text

    def read_text(self, *a, **kw):
        if self.name == "ldap.toml":
            raise PermissionError(13, "Permission denied", str(self))
        return ler(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(ErroConfig, match=f"não foi possível ler .*{tmp_path / 'ldap.toml'}"):
        carregar_config(env)


def test_ldap_toml_bind_pw_file_inexistente(tmp_path):
    env = _env_com_toml(tmp_path)
    (tmp_path / "pw-arquivo").unlink()
    with pytest.raises(ErroConfig, match=f"não foi possível ler .*{tmp_path / 'pw-arquivo'}"):
        carregar_config(env)


def test_segredo_file_inexistente(tmp_path):
    env = _env(tmp_path, SECRET_KEY_FILE=str(tmp_path / "sem-chave"))
    with pytest.raises(ErroConfig, match=f"não foi possível ler .*{tmp_path / 'sem-chave'}"):
        carregar_config(env)


def test_segredo_file_ilegivel_nao_vaza_conteudo(tmp_path):
    (tmp_path / "sk-bin").write_bytes(b"segredo-\xff")
    env = _env(tmp_path, SECRET_KEY_FILE=str(tmp_path / "sk-bin"))
    with pytest.raises(ErroConfig) as erro:
        carregar_config(env)
    assert str(tmp_path / "sk-bin") in str(erro.value) and "segredo-" not in str(erro.value)


def test_convite_ttl_dias(tmp_path):
    assert carregar_config(_env(tmp_path, CONVITE_TTL_DIAS="15")).convite_ttl_dias == 15


@pytest.mark.parametrize("valor", ["0", "-1", "sete", "1.5"])
def test_convite_ttl_dias_invalido(tmp_path, valor):
    with pytest.raises(ErroConfig, match="CONVITE_TTL_DIAS"):
        carregar_config(_env(tmp_path, CONVITE_TTL_DIAS=valor))
