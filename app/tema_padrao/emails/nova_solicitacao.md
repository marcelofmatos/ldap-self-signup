Assunto: {{ plataforma }} — {% if alteracao is defined %}correção de dados para revisar{% else %}nova solicitação de acesso{% endif %}
Botao: Revisar solicitação
Motivo: Você recebeu este e-mail porque é o endereço de aviso dos administradores do cadastro da {{ plataforma }}.

{% if alteracao is defined %}Correção de dados da conta de **{{ nome }}** ({{ email }}) para revisar.{% else %}Nova solicitação confirmada de **{{ nome }}** ({{ email }}).{% endif %}

Revise no painel pelo link abaixo.
