Assunto: {{ plataforma }} — sua conta foi aprovada
Botao: Definir minha senha
Motivo: Você recebeu este e-mail porque sua conta na {{ plataforma }} foi criada.

Olá, {{ nome }}!

Sua conta foi criada. Seu usuário é **{{ uid }}**.
{% if links %}
Com ela você acessa:
{% for rotulo, url in links.items() %}
- {{ rotulo }}: <{{ url }}>
{% endfor %}
{% endif %}
Para começar, defina sua senha no link abaixo. Ele vale por {{ validade }} horas e só pode ser usado uma vez.
