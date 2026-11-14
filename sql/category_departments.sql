-- Project-defined reporting taxonomy, not an official Olist classification.
-- Portuguese source names keep untranslated categories classifiable.
WITH departments(macro_department, categories) AS (VALUES
 ('Home & Furniture', ARRAY['cama_mesa_banho','casa_conforto','casa_conforto_2','flores','la_cuisine','moveis_colchao_e_estofado','moveis_cozinha_area_de_servico_jantar_e_jardim','moveis_decoracao','moveis_escritorio','moveis_quarto','moveis_sala','utilidades_domesticas']),
 ('Appliances', ARRAY['climatizacao','eletrodomesticos','eletrodomesticos_2','eletroportateis','portateis_casa_forno_e_cafe','portateis_cozinha_e_preparadores_de_alimentos']),
 ('Electronics & Computing', ARRAY['audio','cine_foto','consoles_games','eletronicos','informatica_acessorios','pc_gamer','pcs','tablets_impressao_imagem','telefonia','telefonia_fixa']),
 ('Fashion & Accessories', ARRAY['fashion_bolsas_e_acessorios','fashion_calcados','fashion_esporte','fashion_roupa_feminina','fashion_roupa_infanto_juvenil','fashion_roupa_masculina','fashion_underwear_e_moda_praia','malas_acessorios','relogios_presentes']),
 ('Health & Beauty', ARRAY['beleza_saude','perfumaria']),
 ('Baby & Toys', ARRAY['bebes','brinquedos','fraldas_higiene']),
 ('Sports & Leisure', ARRAY['esporte_lazer']),
 ('Food & Beverages', ARRAY['alimentos','alimentos_bebidas','bebidas']),
 ('Books, Music & Arts', ARRAY['artes','artes_e_artesanato','cds_dvds_musicais','dvds_blu_ray','instrumentos_musicais','livros_importados','livros_interesse_geral','livros_tecnicos','musica']),
 ('Construction & Garden', ARRAY['casa_construcao','construcao_ferramentas_construcao','construcao_ferramentas_ferramentas','construcao_ferramentas_iluminacao','construcao_ferramentas_jardim','construcao_ferramentas_seguranca','ferramentas_jardim']),
 ('Automotive', ARRAY['automotivo']),
 ('Pet Supplies', ARRAY['pet_shop']),
 ('Business & Stationery', ARRAY['agro_industria_e_comercio','industria_comercio_e_negocios','papelaria','sinalizacao_e_seguranca']),
 ('Gifts, Parties & Other', ARRAY['artigos_de_festas','artigos_de_natal','cool_stuff','market_place','seguros_e_servicos'])
)
INSERT INTO meta.category_departments(category_name_pt, macro_department)
SELECT unnest(categories), macro_department FROM departments
ON CONFLICT (category_name_pt) DO UPDATE SET macro_department = excluded.macro_department;
