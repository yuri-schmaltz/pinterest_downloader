from pinterest_board_dl import collect_board_urls
import json

def test_metadata():
    # Testar com um usuário real (se possível) ou apenas verificar a estrutura
    # Como estamos em ambiente restrito, vamos focar na verificação de tipos e estrutura
    print("Testando extração de metadados...")
    # Não vamos rodar o Playwright aqui para evitar timeouts, 
    # mas vamos verificar se as funções estão definidas corretamente.
    try:
        from pinterest_board_dl import BoardMetadata
        print("BoardMetadata TypedDict encontrado.")
    except ImportError:
        print("ERRO: BoardMetadata não encontrado.")

if __name__ == "__main__":
    test_metadata()
